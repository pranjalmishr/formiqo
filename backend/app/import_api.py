"""Retained original inspection and explicit, non-destructive editable recreation."""
import shutil
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from .db import get_db,Resume,SourceDocument,EditorDraft,EditorVersion,ResumeVersion,uid,now
from .storage import owner,rate_limit,MIMES
from .auth import aware,retention_expiry
from .config import settings
from .editor_content import DraftContent,seed_content
from .editor_api import fingerprint,get_editor
from .templates import TemplateKey,TEMPLATES

router=APIRouter(prefix='/api/imports',tags=['Resume import and recreation'])


def owned(db,identifier,owner_id):
    resume=db.get(Resume,identifier)
    if not resume or resume.owner!=owner_id or aware(resume.expires_at)<=now():raise HTTPException(404,'Resume not found or expired.')
    return resume


def source_path(source):
    return settings.storage_dir/'originals'/f'{source.resume_id}.{source.format}'


@router.get('/{identifier}')
def inspect(identifier:str,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    resume=owned(db,identifier,owner_id);source=db.get(SourceDocument,identifier);available=bool(source and source_path(source).is_file())
    reconstruction=resume.extraction.get('reconstruction')
    return {'resume_id':resume.id,'filename':resume.filename,'status':resume.status,'error':resume.error,'text':resume.original_text or resume.text,'original_available':available,'format':source.format if source else resume.original_format,'size':source.size if source else None,'expires_at':resume.expires_at.isoformat(),'profile':reconstruction['profile'] if reconstruction else None,'content':reconstruction['content'] if reconstruction else seed_content(resume.original_text or resume.text),'notice':'The original is retained privately until you delete it or the resume expires. Reconstruction is an editable approximation of supported text, hierarchy, typography and column structure—not a pixel-identical replica.' if available else 'This older resume has no retained binary original. Text is preserved; re-upload the source to enable side-by-side recreation.'}


@router.get('/{identifier}/original')
def original(identifier:str,download:bool=False,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    resume=owned(db,identifier,owner_id);source=db.get(SourceDocument,identifier)
    if not source or not source_path(source).is_file():raise HTTPException(410,'No retained original is available for this older upload.')
    mime={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','txt':'text/plain'}[source.format]
    return FileResponse(source_path(source),media_type=mime,filename=source.filename,content_disposition_type='attachment' if download or source.format!='pdf' else 'inline',headers={'Cache-Control':'no-store'})


@router.delete('/{identifier}/original',status_code=204)
def delete_original(identifier:str,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    owned(db,identifier,owner_id);source=db.get(SourceDocument,identifier)
    if source:source_path(source).unlink(missing_ok=True);db.delete(source);db.commit()
    return Response(status_code=204)


class Recreate(BaseModel):
    template:TemplateKey|None=None
    reviewed:bool=False


@router.post('/{identifier}/recreate',status_code=201)
def recreate(identifier:str,data:Recreate,request:Request,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    rate_limit(request,'builder-create');resume=owned(db,identifier,owner_id)
    if not data.reviewed:raise HTTPException(422,'Review the extracted content and uncertainties before creating an editable copy.')
    if resume.status!='ready':raise HTTPException(409,'Wait for successful text extraction before recreation.')
    reconstruction=resume.extraction.get('reconstruction');content=DraftContent.model_validate(reconstruction['content'] if reconstruction else seed_content(resume.original_text or resume.text))
    if data.template:
        content.template=data.template
        if TEMPLATES[data.template]['columns']==1:content.style.columns=None
    new_id=uid();text=content.text();metadata={**resume.extraction,'recreated_from':identifier}
    clone=Resume(id=new_id,owner=owner_id,filename=resume.filename[:140]+' — Recreated',original_format='recreated',text=text,original_text=resume.original_text or resume.text,extraction=metadata,status='ready',expires_at=retention_expiry(owner_id))
    source=db.get(SourceDocument,identifier);copied=None
    try:
        db.add(clone);db.flush()
        if source and source_path(source).is_file():
            copied=settings.storage_dir/'originals'/f'{new_id}.{source.format}';shutil.copyfile(source_path(source),copied);copied.chmod(0o600)
            db.add(SourceDocument(resume_id=new_id,format=source.format,filename=source.filename,size=source.size))
        db.add_all([EditorDraft(resume_id=new_id,content=content.model_dump(),revision=1,source_hash=fingerprint(text),applied=[],rejected=[]),EditorVersion(resume_id=new_id,revision=1,content=content.model_dump(),change_summary='Reviewed editable recreation; original preserved'),ResumeVersion(resume_id=new_id,text=text)])
        db.commit()
    except Exception:
        db.rollback()
        if copied:copied.unlink(missing_ok=True)
        raise HTTPException(503,'The editable copy could not be saved. The original resume was not changed.')
    return get_editor(new_id,owner_id,db)
