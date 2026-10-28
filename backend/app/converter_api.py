"""Private asynchronous conversion jobs. Inputs removed after processing.

Jobs are durable DB records. Interrupted jobs are marked failed on startup;
clients can safely re-upload. Only two conversion subprocesses run at once.
"""
import asyncio
import json
import os
import signal
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, BackgroundTasks, Response
from fastapi.responses import FileResponse
from .persistence import find, remove_where
from sqlalchemy.orm import Session as DBSession
from PIL import Image
from .config import settings
from .db import Session, ConversionJob, DocumentRecord, AuthSession, AuthToken, get_db, now, uid
from .storage import owner, rate_limit, safe_filename, validate_signature
from .auth import retention_expiry, aware
from .conversion import ConversionSettings, MIMES, IMAGE_TYPES, matrix, office_available
from .processing import native_slots

router=APIRouter(prefix='/api/converter',tags=['Document conversion'])
_slots=native_slots
_pending=set()
_processes={}


def job_dir(identifier):
    if not __import__('re').fullmatch(r'[a-f0-9-]{36}',identifier): raise HTTPException(404,'Job not found.')
    return settings.storage_dir/'jobs'/identifier


def remove_job_files(identifier):
    process=_processes.get(identifier)
    if process and process.poll() is None:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    shutil.rmtree(job_dir(identifier),ignore_errors=True)


def require_job(db,identifier,owner_id):
    row=db.get(ConversionJob,identifier)
    if not row or row.owner!=owner_id or aware(row.expires_at)<=now(): raise HTTPException(404,'Conversion not found or expired.')
    return row


def serialize(job):
    return {'id':job.id,'source_filename':job.source_filename,'source_format':job.source_format,'target_format':job.target_format,'status':job.status,'progress':job.progress,'outputs':job.outputs,'warnings':job.warnings,'error':job.error,'error_code':job.error_code,'duration_ms':job.duration_ms,'created_at':job.created_at.isoformat(),'completed_at':job.completed_at.isoformat() if job.completed_at else None,'expires_at':job.expires_at.isoformat(),'settings':job.settings,'inputs':[{k:v for k,v in item.items() if k!='path'} for item in job.inputs]}


def validate_input(path,ext,mime):
    if mime.split(';')[0] not in {MIMES.get(ext),'application/zip' if ext in ('docx','pptx','xlsx') else MIMES.get(ext)}:
        raise HTTPException(415,'The MIME type does not match the source format.')
    if ext in ('pdf','docx','txt'): validate_signature(path,ext)
    elif ext in IMAGE_TYPES:
        # Only cheap byte signatures run in the API process. Full codec/header,
        # dimension and pixel validation runs inside the bounded native worker.
        with path.open('rb') as stream:head=stream.read(16)
        valid=head.startswith(b'\xff\xd8\xff') if ext=='jpg' else head.startswith(b'\x89PNG\r\n\x1a\n') if ext=='png' else head[:4]==b'RIFF' and head[8:12]==b'WEBP'
        if not valid:raise HTTPException(422,'The image signature does not match its claimed format.')
    elif ext=='html':
        try:
            text=path.read_text(encoding='utf-8-sig')
            if '\x00' in text or not __import__('re').search(r'<[a-zA-Z][^>]*>',text): raise ValueError()
        except (ValueError,UnicodeError): raise HTTPException(422,'Upload a valid UTF-8 HTML document.')
    elif ext in ('xlsx','pptx'):
        try:
            with zipfile.ZipFile(path) as z:
                infos=z.infolist(); names=z.namelist(); required='xl/workbook.xml' if ext=='xlsx' else 'ppt/presentation.xml'
                if required not in names or '[Content_Types].xml' not in names: raise ValueError()
                if len(infos)>2000 or sum(i.file_size for i in infos)>40*1024*1024 or any(i.file_size/max(i.compress_size,1)>200 for i in infos): raise ValueError()
                if any('vbaproject' in n.lower() or '..' in Path(n).parts or n.startswith('/') for n in names): raise ValueError()
        except (ValueError,zipfile.BadZipFile): raise HTTPException(422,'Invalid, oversized or macro-enabled Office archive.')
    elif ext=='doc':
        if path.read_bytes()[:8]!=bytes.fromhex('D0CF11E0A1B11AE1'): raise HTTPException(422,'Invalid legacy DOC signature.')
        # Legacy binary macros cannot be reliably inspected, so this format is not
        # advertised by the public upload surface even if an Office engine exists.
        raise HTTPException(415,'Legacy DOC is not accepted for safe processing. Save it as macro-free DOCX or PDF first.')
    else: raise HTTPException(415,'Unsupported source format.')


def execute_job(identifier):
    directory=job_dir(identifier)
    scratch=directory/'scratch';scratch.mkdir(parents=True,exist_ok=True,mode=0o700)
    process=subprocess.Popen([sys.executable,'-m','app.conversion_worker',str(directory.resolve())],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={**os.environ,'OMP_THREAD_LIMIT':'1','TMPDIR':str(scratch.resolve())})
    _processes[identifier]=process
    try:
        stdout,_=process.communicate(timeout=settings.conversion_timeout)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        process.communicate()
        return {'error':'Conversion timed out. Try fewer pages or a smaller document.','error_code':'timeout'}
    finally:
        _processes.pop(identifier,None)
        shutil.rmtree(scratch,ignore_errors=True)
    try:
        result=json.loads(stdout)
        if process.returncode and 'error' not in result: raise ValueError()
        return result
    except (ValueError,UnicodeError): return {'error':'The conversion worker failed safely. Re-export the source and retry.','error_code':'worker_failed'}


async def process_job(identifier):
    started=time.monotonic()
    try:
        async with _slots:
            with Session() as db:
                row=db.get(ConversionJob,identifier)
                if not row: return
                row.status='processing';row.progress=20;db.commit()
            result=await asyncio.to_thread(execute_job,identifier)
            with Session() as db:
                row=db.get(ConversionJob,identifier)
                if not row:
                    remove_job_files(identifier);return
                if result.get('error'):
                    row.status='failed';row.error=result['error'];row.error_code=result.get('error_code','processing_failed')
                    shutil.rmtree(job_dir(identifier)/'outputs',ignore_errors=True)
                elif 'inspection' in result:
                    row.settings={**row.settings,'_inspection':result['inspection']};row.status='prepared';row.progress=0
                else:
                    # Worker already opened/validated each output; verify manifest paths too.
                    outputs=result.get('outputs',[])
                    if not outputs or any(Path(o['filename']).name!=o['filename'] or not (job_dir(identifier)/'outputs'/o['filename']).is_file() for o in outputs):
                        raise ValueError('Invalid output manifest')
                    row.outputs=outputs;row.warnings=result.get('warnings',[]);row.status='completed';row.progress=100
                    db.add(DocumentRecord(owner=row.owner,job_id=row.id,filename=Path(row.source_filename).stem+'.'+row.target_format,format=row.target_format))
                row.completed_at=now();row.duration_ms=int((time.monotonic()-started)*1000);db.commit()
    except Exception:
        with Session() as db:
            row=db.get(ConversionJob,identifier)
            if row:
                row.status='failed';row.error='Conversion failed safely. Check available storage or upload a fresh document.';row.error_code='processing_failed';row.completed_at=now();db.commit()
                shutil.rmtree(job_dir(identifier)/'outputs',ignore_errors=True)
    finally:
        with Session() as db:
            retained=db.get(ConversionJob,identifier)
            if not retained or retained.status!='prepared':shutil.rmtree(job_dir(identifier)/'inputs',ignore_errors=True)
        (job_dir(identifier)/'request.json').unlink(missing_ok=True)
        _pending.discard(identifier)


@router.get('/supported-formats')
def supported():
    supported_matrix=matrix(); supported_matrix.pop('doc',None)
    return {'matrix':supported_matrix,'max_upload_mb':settings.max_upload_mb,'max_files':10,'max_pages':settings.max_pages,'ocr_available':bool(shutil.which('tesseract')),'office_available':office_available(),'dpi_presets':[72,150,200],'warnings':['PDF-to-Word reconstructs editable text/basic structure; complex formatting may need cleanup.','Scanned PDF text conversions require Tesseract OCR.','DOCX/PowerPoint/Excel PDF rendering requires enabled sandboxed LibreOffice. Legacy DOC is different from DOCX and is not accepted.']}


@router.post('/jobs',status_code=202)
async def create_job(request:Request,background:BackgroundTasks,files:list[UploadFile]=File(...),target:str=Form(...),options:str=Form('{}'),owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    rate_limit(request,'conversions')
    if not 1<=len(files)<=10: raise HTTPException(422,'Upload 1–10 files. Multiple inputs are only for images to PDF.')
    if len(_pending)>=20: raise HTTPException(503,'Conversion queue is full. Retry shortly.')
    try: validated=ConversionSettings.model_validate_json(options)
    except ValueError: raise HTTPException(422,'Invalid conversion settings. Check resolution, page range, size and margins.')
    identifier=uid();directory=job_dir(identifier);inputs=directory/'inputs';outputs=directory/'outputs'
    try:
        inputs.mkdir(parents=True,mode=0o700);outputs.mkdir(mode=0o700)
    except OSError:
        shutil.rmtree(directory,ignore_errors=True)
        for file in files: await file.close()
        raise HTTPException(507,'Temporary storage is unavailable. Check disk space and permissions, then retry.')
    _pending.add(identifier)
    entries=[];total=0;source=None
    try:
        for index,file in enumerate(files):
            filename=safe_filename(file.filename or 'document');ext=Path(filename).suffix.lower().lstrip('.')
            if ext=='jpeg': ext='jpg'
            if source and ext!=source and not (source in IMAGE_TYPES and ext in IMAGE_TYPES and target=='pdf'): raise HTTPException(422,'Mixed source formats are only supported for images to PDF.')
            source=source or ext
            if ext not in matrix() or ext=='doc' or target not in matrix()[ext]: raise HTTPException(415,'This source/target pair is not supported on the current backend.')
            path=inputs/f'input-{index:02d}.{ext}';size=0
            with path.open('xb') as out:
                path.chmod(0o600)
                while chunk:=await file.read(65536):
                    size+=len(chunk);total+=len(chunk)
                    if total>settings.max_upload_mb*1024*1024: raise HTTPException(413,'Total upload exceeds the configured size limit.')
                    out.write(chunk)
            if not size: raise HTTPException(422,'An uploaded document is empty.')
            validate_input(path,ext,file.content_type or '')
            entries.append({'filename':filename,'path':path.name})
        if len(entries)>1 and not (source in IMAGE_TYPES and target=='pdf'): raise HTTPException(422,'Multiple inputs are only supported for images to one PDF.')
        payload={'inputs':[e['path'] for e in entries],'source':source,'target':target,'settings':validated.model_dump()}
        (directory/'request.json').write_text(json.dumps(payload),encoding='utf-8')
        row=ConversionJob(id=identifier,owner=owner_id,source_filename=entries[0]['filename'] if len(entries)==1 else f'{len(entries)} images',source_format=source if len(entries)==1 else 'images',target_format=target,settings=validated.model_dump(),inputs=entries,expires_at=retention_expiry(owner_id))
        db.add(row);db.commit();_pending.add(identifier);background.add_task(process_job,identifier)
        return serialize(row)
    except OSError:
        _pending.discard(identifier);db.rollback();shutil.rmtree(directory,ignore_errors=True)
        raise HTTPException(507,'Not enough temporary storage for this upload. Check disk space and retry.')
    except Exception:
        _pending.discard(identifier);db.rollback();shutil.rmtree(directory,ignore_errors=True);raise
    finally:
        for file in files: await file.close()


@router.get('/jobs')
def list_jobs(offset:int=0,limit:int=50,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    if offset<0 or not 1<=limit<=100: raise HTTPException(422,'Invalid pagination range.')
    rows=find(db,ConversionJob,[('owner','==',owner_id),('expires_at','>',now())],[('created_at','desc')],limit=limit,offset=offset)
    return {'items':[serialize(r) for r in rows],'offset':offset,'limit':limit}


@router.get('/jobs/{identifier}')
def get_job(identifier:str,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    return serialize(require_job(db,identifier,owner_id))


@router.get('/jobs/{identifier}/download')
def download(identifier:str,index:int=0,inline:bool=False,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    row=require_job(db,identifier,owner_id)
    if row.status!='completed': raise HTTPException(409,'This conversion has no completed output yet.')
    if not 0<=index<len(row.outputs): raise HTTPException(404,'Output not found.')
    output=row.outputs[index];name=output['filename'];path=job_dir(identifier)/'outputs'/name
    if Path(name).name!=name or not path.is_file(): raise HTTPException(410,'Output is no longer available. Convert the source again.')
    # No public static file URLs; every request authorizes the owner and expiry.
    disposition='inline' if inline and output['format'] in ('pdf','jpg','png','webp') else 'attachment'
    return FileResponse(path,media_type=output['mime'],filename=name,content_disposition_type=disposition,headers={'Cache-Control':'no-store'})


@router.delete('/jobs/{identifier}',status_code=204)
def delete_job(identifier:str,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    row=require_job(db,identifier,owner_id)
    remove_where(db,DocumentRecord,[('job_id','==',identifier)]);db.delete(row);db.commit();remove_job_files(identifier)
    return Response(status_code=204)


def cleanup_jobs():
    with Session() as db:
        rows=find(db,ConversionJob,[('expires_at','<',now())])
        for row in rows:
            remove_where(db,DocumentRecord,[('job_id','==',row.id)]);db.delete(row);remove_job_files(row.id)
        remove_where(db,AuthSession,[('expires_at','<',now())])
        remove_where(db,AuthToken,[('expires_at','<',now())])
        db.commit()
    root=settings.storage_dir/'jobs'
    if root.exists():
        for path in root.iterdir():
            if path.is_dir() and path.stat().st_mtime<time.time()-settings.retention_hours*3600:
                with Session() as db:
                    if not db.get(ConversionJob,path.name): shutil.rmtree(path,ignore_errors=True)


def recover_jobs():
    with Session() as db:
        for row in find(db,ConversionJob,[('status','in',['queued','processing'])]):
            row.status='failed';row.error='Server restarted during conversion. Upload again to retry safely.';row.error_code='interrupted';row.completed_at=now();remove_job_files(row.id)
        db.commit()
