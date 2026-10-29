"""Prepared document workspaces, owned thumbnails and explicit run/cancel stages."""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request,Response,UploadFile,File,Form,BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session as DBSession
from .persistence import change_where
from .db import get_db,ConversionJob,uid
from .storage import owner,rate_limit,safe_filename
from .auth import retention_expiry
from .config import settings
from .conversion import matrix,ConversionSettings
from .document_tools import TOOLS,ToolSettings
from .converter_api import job_dir,require_job,serialize,validate_input,process_job,_pending
from .processing import native_slots
from .native_env import worker_env
from . import durable_files

router=APIRouter(prefix='/api/tools',tags=['Professional document tools'])


def catalog():
 items=[{'id':key,**value,'available':True} for key,value in TOOLS.items()]
 names={'pdf':'PDF','docx':'Word','txt':'TXT','jpg':'JPG','png':'PNG','webp':'WEBP','html':'HTML','pptx':'PowerPoint','xlsx':'Excel'}
 for source,targets in matrix().items():
  if source=='doc':continue
  for target in targets:
   category='PDF conversions' if source=='pdf' else 'Image conversions' if source in ('jpg','png','webp') else 'Office conversions' if source in ('pptx','xlsx') else 'Document conversions'
   items.append({'id':'convert-'+source+'-'+target,'name':names.get(source,source)+' to '+names.get(target,target),'description':'Convert privately with source inspection, relevant settings and validated output.','category':category,'sources':[source],'target':target,'multiple':source in ('jpg','png','webp') and target=='pdf','available':True,'conversion':True})
 for source,label in [('docx','Word to PDF'),('pptx','PowerPoint to PDF'),('xlsx','Excel to PDF')]:
  if 'pdf' not in matrix().get(source,[]):items.append({'id':'convert-'+source+'-pdf','name':label,'description':'Requires enabled, sandboxed LibreOffice; unavailable on this backend.','category':'Office conversions','sources':[source],'target':'pdf','available':False})
 return items


@router.get('/catalog')
def tools():return {'items':catalog(),'max_upload_mb':settings.max_upload_mb,'max_files':10,'notice':'Only available tools can be opened. Unsupported Office utilities are labeled unavailable, not simulated.'}


@router.post('/prepare',status_code=202)
async def prepare(request:Request,background:BackgroundTasks,tool:str=Form(...),files:list[UploadFile]=File(...),owner_id=Depends(owner),db:DBSession=Depends(get_db)):
 rate_limit(request,'conversions');definition=next((item for item in catalog() if item['id']==tool and item['available']),None)
 if not definition:raise HTTPException(415,'This tool is unavailable or unsupported by the configured backend.')
 if not 1<=len(files)<=10 or (len(files)>1 and not definition.get('multiple')):raise HTTPException(422,'This tool does not accept that number of files.')
 if len(_pending)>=20:raise HTTPException(503,'Native processing queue is full. Retry shortly.')
 identifier=uid();directory=job_dir(identifier);inputs=directory/'inputs';outputs=directory/'outputs';entries=[];total=0
 try:
  inputs.mkdir(parents=True,mode=0o700);outputs.mkdir(mode=0o700);_pending.add(identifier)
  for index,file in enumerate(files):
   name=safe_filename(file.filename or 'document');ext=Path(name).suffix.lower().lstrip('.');ext='jpg' if ext=='jpeg' else ext
   allowed=definition['sources']
   if definition.get('conversion') and definition.get('multiple'):allowed=['jpg','png','webp']
   if ext not in allowed:raise HTTPException(415,'Upload a supported input for this specific tool: '+', '.join(allowed))
   path=inputs/f'input-{index:02d}.{ext}'
   with path.open('xb') as stream:
    path.chmod(0o600)
    while chunk:=await file.read(65536):
     total+=len(chunk)
     if total>settings.max_upload_mb*1024*1024:raise HTTPException(413,'Combined input exceeds the upload limit.')
     stream.write(chunk)
   if not path.stat().st_size:raise HTTPException(422,'An input is empty.')
   validate_input(path,ext,file.content_type or '')
   entries.append({'filename':name,'path':path.name,'format':ext,'size':path.stat().st_size})
  target=entries[0]['format'] if definition['target']=='source' else definition['target']
  spec={'inspection_only':True,'inputs':[e['path'] for e in entries],'formats':[e['format'] for e in entries],'source':entries[0]['format'],'target':target,'settings':{}}
  (directory/'request.json').write_text(json.dumps(spec))
  job=ConversionJob(id=identifier,owner=owner_id,source_filename=entries[0]['filename'] if len(entries)==1 else str(len(entries))+' documents',source_format=entries[0]['format'] if len(entries)==1 else 'batch',target_format=target,settings={'_tool_id':tool,'_phase':'inspect'},inputs=entries,expires_at=retention_expiry(owner_id))
  db.add(job);db.commit()
  if settings.vercel_serverless:
   await process_job(identifier);db.refresh(job)
  else:background.add_task(process_job,identifier)
  return serialize(job)
 except OSError:
  db.rollback();_pending.discard(identifier);shutil.rmtree(directory,ignore_errors=True);raise HTTPException(507,'Private workspace storage is unavailable. Check disk space and retry.')
 except Exception:
  db.rollback();_pending.discard(identifier);shutil.rmtree(directory,ignore_errors=True);raise
 finally:
  for file in files:await file.close()


class Run(BaseModel):
 settings:dict=Field(default_factory=dict)
 file_order:list[int]=Field(default_factory=list,max_length=10)


@router.post('/{identifier}/run',status_code=202)
async def run(identifier:str,data:Run,request:Request,background:BackgroundTasks,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
 rate_limit(request,'tool-runs');row=require_job(db,identifier,owner_id)
 if row.status!='prepared':raise HTTPException(409,'Wait for successful inspection before running, or prepare a fresh workspace.')
 tool=row.settings.get('_tool_id');definition=next((item for item in catalog() if item['id']==tool and item['available']),None)
 if not definition:raise HTTPException(415,'This tool is no longer available.')
 try:options=ConversionSettings.model_validate(data.settings).model_dump() if definition.get('conversion') else ToolSettings.model_validate(data.settings).model_dump()
 except ValueError:raise HTTPException(422,'Invalid operation settings. Check ranges, dimensions, rotation and quality.')
 if tool=='pdf-delete' and not options.get('pages'):raise HTTPException(422,'Select at least one page to delete.')
 directory=job_dir(identifier)
 await asyncio.to_thread(durable_files.inputs,row)
 if any(not (directory/'inputs'/entry['path']).is_file() for entry in row.inputs):raise HTTPException(410,'Prepared input files are no longer available. Upload again.')
 spec={'inputs':[e['path'] for e in row.inputs],'formats':[e['format'] for e in row.inputs],'source':row.inputs[0]['format'],'target':row.target_format,'settings':options}
 if not definition.get('conversion'):spec['operation']=tool
 # Preserve requested file order for combined-image conversion as well.
 if definition.get('conversion') and len(row.inputs)>1:
  order=data.file_order or list(range(len(row.inputs)))
  if sorted(order)!=list(range(len(row.inputs))):raise HTTPException(422,'Input order must contain every file once.')
  spec['inputs']=[row.inputs[i]['path'] for i in order];spec['formats']=[row.inputs[i]['format'] for i in order]
 if len(_pending)>=20:raise HTTPException(503,'Processing queue is full. Your prepared input remains available; retry shortly.')
 requested_order=data.file_order or options.get('file_order') or list(range(len(row.inputs)))
 changed=change_where(db,ConversionJob,[('id','==',identifier),('owner','==',owner_id),('status','==','prepared')],dict(status='queued',progress=0,error=None,settings={**row.settings,**options,'_phase':'run','_input_order':requested_order}))
 if changed!=1:db.rollback();raise HTTPException(409,'This workspace was already run or canceled. Refresh its status.')
 try:(directory/'request.json').write_text(json.dumps(spec))
 except OSError:db.rollback();raise HTTPException(507,'The operation could not be staged. Check workspace storage and retry.')
 db.commit();db.refresh(row);_pending.add(identifier)
 if settings.vercel_serverless:
  await process_job(identifier);db.refresh(row)
 else:background.add_task(process_job,identifier)
 return serialize(row)


def thumbnail_worker(path,fmt,target,page):
 result=subprocess.run([sys.executable,'-m','app.tool_preview_worker',str(path.resolve()),fmt,str(target.resolve()),str(page)],capture_output=True,timeout=20,check=False,env=worker_env(target.parent))
 if result.returncode or not target.is_file():raise ValueError('Thumbnail generation failed')


@router.get('/{identifier}/thumbnail')
async def preview(identifier:str,input:int=0,page:int=1,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
 row=require_job(db,identifier,owner_id)
 if not 0<=input<len(row.inputs) or not 1<=page<=settings.max_pages:raise HTTPException(404,'Preview not found.')
 directory=job_dir(identifier);cache=directory/'previews';cache.mkdir(parents=True,exist_ok=True,mode=0o700);target=cache/f'{input}-{page}.png'
 if not await asyncio.to_thread(durable_files.hydrate,target):
  entry=row.inputs[input];source=directory/'inputs'/entry['path']
  if not await asyncio.to_thread(durable_files.hydrate,source):raise HTTPException(410,'Source preview is no longer available; download the validated output instead.')
  async with native_slots:
   try:await asyncio.to_thread(thumbnail_worker,source,entry['format'],target,page)
   except Exception:raise HTTPException(422,'This preview could not be rendered safely.')
  await asyncio.to_thread(durable_files.persist,target)
 return FileResponse(target,media_type='image/png',headers={'Cache-Control':'private, max-age=60'})


@router.get('/{identifier}/output-thumbnail')
async def output_preview(identifier:str,index:int=0,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
 row=require_job(db,identifier,owner_id)
 if row.status!='completed' or not 0<=index<len(row.outputs):raise HTTPException(404,'Output preview not found.')
 output=row.outputs[index]
 if output['format'] not in ('pdf','jpg','png','webp'):raise HTTPException(415,'This output format has no native thumbnail.')
 directory=job_dir(identifier);cache=directory/'previews';cache.mkdir(parents=True,exist_ok=True,mode=0o700);target=cache/f'output-{index}.png'
 if not await asyncio.to_thread(durable_files.hydrate,target):
  source=directory/'outputs'/output['filename']
  if not await asyncio.to_thread(durable_files.hydrate,source):raise HTTPException(410,'Output is no longer available.')
  async with native_slots:
   try:await asyncio.to_thread(thumbnail_worker,directory/'outputs'/output['filename'],output['format'],target,1)
   except Exception:raise HTTPException(422,'Output thumbnail unavailable; download the validated document instead.')
  await asyncio.to_thread(durable_files.persist,target)
 return FileResponse(target,media_type='image/png',headers={'Cache-Control':'private, max-age=60'})
