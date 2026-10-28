"""Unified owned document library and deletion cascade, without duplicating file bytes."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session as DBSession
from .db import get_db, Resume, Analysis, ResumeVersion, EditorDraft, EditorVersion, BuilderDraft, SourceDocument, ConversionJob, DocumentRecord, now
from .storage import owner, safe_filename, remove_source
from .auth import aware

router=APIRouter(prefix='/api/documents',tags=['Document library'])


def remove_resume(db,r):
    for model in [Analysis,ResumeVersion,EditorVersion,EditorDraft,BuilderDraft,SourceDocument]: db.execute(delete(model).where(model.resume_id==r.id))
    db.delete(r);remove_source(r.id,include_original=True)


def remove_conversion(db,job):
    from .converter_api import remove_job_files
    db.execute(delete(DocumentRecord).where(DocumentRecord.job_id==job.id));db.delete(job);remove_job_files(job.id)


def delete_owned_data(db,owner_id):
    for r in db.scalars(select(Resume).where(Resume.owner==owner_id)).all(): remove_resume(db,r)
    for job in db.scalars(select(ConversionJob).where(ConversionJob.owner==owner_id)).all(): remove_conversion(db,job)


def resume_item(db,r):
    latest=db.scalar(select(Analysis).where(Analysis.resume_id==r.id).order_by(Analysis.created_at.desc()).limit(1))
    return {'id':r.id,'kind':'resume','filename':r.filename,'format':r.original_format,'category':'resume','created_at':r.created_at.isoformat(),'updated_at':r.updated_at.isoformat(),'expires_at':r.expires_at.isoformat(),'status':r.status,'error':r.error,'latest_score':latest.overall_score if latest else None,'latest_analysis_id':latest.id if latest else None,'has_builder':db.get(BuilderDraft,r.id)is not None,'download_url':'/api/resumes/'+r.id+'/download','open_url':'/app/editor?resume='+r.id,'analyze_url':'/app/checker?resume='+r.id}


def conversion_item(doc,job):
    primary=next((index for index,o in enumerate(job.outputs) if o['format']=='zip'),0)
    tool=job.settings.get('_tool_id')
    open_url=('/app/tools/'+tool if tool else '/app/converter/legacy')+'?job='+job.id
    preview=next((index for index,output in enumerate(job.outputs) if output['format'] in ('pdf','jpg','png','webp')),None)
    return {'id':doc.id,'kind':'conversion','filename':doc.filename,'format':doc.format,'category':'converted','created_at':doc.created_at.isoformat(),'updated_at':doc.updated_at.isoformat(),'expires_at':job.expires_at.isoformat(),'status':job.status,'latest_score':None,'job_id':job.id,'download_url':f'/api/converter/jobs/{job.id}/download?index={primary}','open_url':open_url,'preview_url':f'/api/tools/{job.id}/output-thumbnail?index={preview}' if preview is not None else None,'analyze_url':None,'has_builder':False}


@router.get('')
def documents(offset:int=0,limit:int=50,q:str='',category:str='all',sort:str='recent',owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    if not 0<=offset<=10000 or not 1<=limit<=100 or len(q)>200: raise HTTPException(422,'Invalid search or pagination.')
    if category not in ('all','resume','converted','pdf','docx','images','builder','txt'): raise HTTPException(422,'Invalid document category.')
    if sort not in ('recent','oldest','name'):raise HTTPException(422,'Unsupported document sort.')
    # Fetch page-size-bounded subsets in SQL, then merge by updated timestamp.
    from sqlalchemy import or_
    search='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    resumes=select(Resume).where(Resume.owner==owner_id,Resume.expires_at>now(),Resume.filename.ilike(search,escape='\\'))
    if category in ('pdf','docx','txt','builder'): resumes=resumes.where(Resume.original_format==category)
    if category in ('converted','images'): resumes=resumes.where(Resume.id=='__none__')
    resume_order=func.lower(Resume.filename).asc() if sort=='name' else Resume.updated_at.asc() if sort=='oldest' else Resume.updated_at.desc()
    rs=db.scalars(resumes.order_by(resume_order).limit(offset+limit)).all()
    query=select(DocumentRecord,ConversionJob).join(ConversionJob,ConversionJob.id==DocumentRecord.job_id).where(DocumentRecord.owner==owner_id,ConversionJob.owner==owner_id,ConversionJob.expires_at>now(),DocumentRecord.filename.ilike(search,escape='\\'))
    if category in ('resume','builder'): query=query.where(DocumentRecord.id=='__none__')
    if category in ('pdf','docx','txt'): query=query.where(DocumentRecord.format==category)
    if category=='images': query=query.where(DocumentRecord.format.in_(['jpg','png','webp']))
    converted_order=func.lower(DocumentRecord.filename).asc() if sort=='name' else DocumentRecord.updated_at.asc() if sort=='oldest' else DocumentRecord.updated_at.desc()
    cs=db.execute(query.order_by(converted_order).limit(offset+limit)).all()
    items=[resume_item(db,r) for r in rs]+[conversion_item(d,j) for d,j in cs]
    items.sort(key=lambda row:row['filename'].casefold() if sort=='name' else row['updated_at'],reverse=sort=='recent')
    return {'items':items[offset:offset+limit],'offset':offset,'limit':limit,'has_more':len(items)>offset+limit or len(rs)==offset+limit or len(cs)==offset+limit}


def owned_record(db,identifier,owner_id):
    r=db.get(Resume,identifier)
    if r and r.owner==owner_id and aware(r.expires_at)>now(): return r,None
    doc=db.get(DocumentRecord,identifier)
    job=db.get(ConversionJob,doc.job_id) if doc else None
    if doc and job and doc.owner==owner_id and job.owner==owner_id and aware(job.expires_at)>now(): return doc,job
    raise HTTPException(404,'Document not found or expired.')


@router.get('/{identifier}')
def get_document(identifier:str,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    record,job=owned_record(db,identifier,owner_id)
    return conversion_item(record,job) if job else resume_item(db,record)


class Rename(BaseModel):
    filename:str=Field(min_length=1,max_length=180)
    @field_validator('filename')
    @classmethod
    def clean_name(cls,value):
        clean=safe_filename(value)
        if clean!=value.strip() or not clean: raise ValueError('Use a simple filename without path separators or control characters')
        return clean


@router.patch('/{identifier}')
def rename(identifier:str,data:Rename,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    record,job=owned_record(db,identifier,owner_id)
    record.filename=data.filename;record.updated_at=now();db.commit()
    return conversion_item(record,job) if job else resume_item(db,record)


@router.delete('/{identifier}',status_code=204)
def delete_document(identifier:str,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    record,job=owned_record(db,identifier,owner_id)
    if job: remove_conversion(db,job)
    else: remove_resume(db,record)
    db.commit();return Response(status_code=204)
