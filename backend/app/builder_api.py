"""Module 3: user-owned guided builder with transactional editor synchronization."""
import asyncio
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from .persistence import resume_children, change_where
from sqlalchemy.orm import Session as DBSession
from .builder_content import BuilderData, BuilderSave, to_content, export_issues
from .db import get_db, Resume, ResumeVersion, BuilderDraft, EditorDraft, EditorVersion, now, uid
from .editor_api import require, fingerprint
from .exports import pdf_bytes, docx_bytes
from .storage import owner, rate_limit
from .config import settings
from .templates import TEMPLATES
from .auth import retention_expiry

router = APIRouter(prefix='/api/builder', tags=['Resume builder'])


def synchronized(draft, resume, editor):
    return bool(editor and draft.source_hash == fingerprint(resume.text) and editor.revision == draft.editor_revision and editor.source_hash == draft.source_hash)


def serialize(draft, resume, editor):
    data = BuilderData.model_validate(draft.data)
    return {'resume_id': resume.id, 'filename': resume.filename, 'revision': draft.revision, 'data': draft.data, 'content': to_content(data).model_dump(), 'out_of_sync': not synchronized(draft, resume, editor), 'export_issues': export_issues(data), 'updated_at': draft.updated_at.isoformat(), 'expires_at': resume.expires_at.isoformat()}


@router.get('/templates')
def templates():
    return {'items': [{'id': key, **value} for key, value in TEMPLATES.items()], 'notice': 'Template structures differ. Simple layouts prioritize a single reading stream; columns and sidebars require extraction review. None guarantees compatibility with every ATS.'}


@router.post('/preview')
def preview(data: BuilderData, request: Request, owner_id=Depends(owner)):
    rate_limit(request, 'builder-preview', limit=300)
    return {'content': to_content(data).model_dump(), 'export_issues': export_issues(data)}


@router.get('')
def list_drafts(offset: int = 0, limit: int = 50, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    if offset < 0 or not 1 <= limit <= 100: raise HTTPException(422, 'Invalid pagination range.')
    rows = [(draft,resume,db.get(EditorDraft,resume.id)) for draft,resume in resume_children(db,BuilderDraft,owner_id,order_field='updated_at')]
    rows = [row for row in rows if row[2] is not None][offset:offset+limit]
    return {'items': [serialize(draft, resume, editor) for draft, resume, editor in rows], 'offset': offset, 'limit': limit}


@router.post('/create', status_code=201)
def create(data: BuilderData, request: Request, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    rate_limit(request, 'builder-create')
    content = to_content(data)
    text = content.text()
    identifier = uid()
    filename = ((data.contact.name.strip() or 'Untitled')[:100] + ' — Resume')
    resume = Resume(id=identifier, owner=owner_id, filename=filename, original_format='builder', text=text, original_text=text, extraction={'format': 'builder', 'page_count': None, 'ocr_pages': [], 'warnings': [], 'checks': ['Structured single-column content; no upload extraction required'], 'limited_layout_detection': True}, status='ready', expires_at=retention_expiry(owner_id))
    db.add(resume)
    db.flush()
    editor = EditorDraft(resume_id=identifier, content=content.model_dump(), revision=1, source_hash=fingerprint(text), applied=[], rejected=[])
    draft = BuilderDraft(resume_id=identifier, data=data.model_dump(), revision=1, source_hash=fingerprint(text), editor_revision=1)
    db.add_all([editor, draft, ResumeVersion(resume_id=identifier, text=text), EditorVersion(resume_id=identifier, revision=1, content=content.model_dump(), change_summary='Created in Formiqo Resume Builder')])
    db.commit()
    return serialize(draft, resume, editor)


@router.get('/{identifier}')
def get_draft(identifier: str, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    resume = require(db, identifier, owner_id)
    draft = db.get(BuilderDraft, identifier)
    if not draft: raise HTTPException(404, 'This resume was not created in the guided builder. Open it in the resume editor instead.')
    return serialize(draft, resume, db.get(EditorDraft, identifier))


@router.patch('/{identifier}')
def save(identifier: str, payload: BuilderSave, request: Request, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    rate_limit(request, 'builder-saves', limit=600)
    resume = require(db, identifier, owner_id)
    draft = db.get(BuilderDraft, identifier)
    editor = db.get(EditorDraft, identifier)
    if not draft: raise HTTPException(404, 'Builder draft not found.')
    if draft.revision != payload.revision: raise HTTPException(409, 'A newer builder draft exists. Reload it before saving; no changes were overwritten.')
    if not synchronized(draft, resume, editor):
        raise HTTPException(409, 'This resume changed in the editor or checker. Open the newer editor draft, or save your builder form as a separate copy to avoid overwriting it.')
    data = payload.data
    if draft.data == data.model_dump(): return serialize(draft, resume, editor)
    content = to_content(data)
    text = content.text()
    expected_editor_revision = draft.editor_revision
    revision, editor_revision = draft.revision + 1, editor.revision + 1
    a = change_where(db,BuilderDraft,[('resume_id','==',identifier),('revision','==',payload.revision)],dict(data=data.model_dump(),revision=revision,source_hash=fingerprint(text),editor_revision=editor_revision,updated_at=now()))
    b = change_where(db,EditorDraft,[('resume_id','==',identifier),('revision','==',expected_editor_revision)],dict(content=content.model_dump(),revision=editor_revision,source_hash=fingerprint(text),updated_at=now()))
    c = change_where(db,Resume,[('id','==',identifier),('text','==',resume.text)],dict(text=text,filename=((data.contact.name.strip() or 'Untitled')[:100] + ' — Resume'),updated_at=now()))
    if any(result != 1 for result in [a, b, c]):
        db.rollback()
        raise HTTPException(409, 'The resume changed while saving. Reload before retrying; no changes were overwritten.')
    db.add_all([ResumeVersion(resume_id=identifier, text=text), EditorVersion(resume_id=identifier, revision=editor_revision, content=content.model_dump(), change_summary='Saved guided builder step '+str(data.step))])
    db.commit()
    for record in [draft, resume, editor]: db.refresh(record)
    return serialize(draft, resume, editor)


@router.post('/{identifier}/export')
async def export(identifier: str, request: Request, format: Literal['pdf', 'docx'], owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    rate_limit(request, 'exports')
    resume = require(db, identifier, owner_id)
    draft = db.get(BuilderDraft, identifier)
    if not draft: raise HTTPException(404, 'Builder draft not found.')
    if not synchronized(draft, resume, db.get(EditorDraft, identifier)):
        raise HTTPException(409, 'Newer editor or checker changes exist. Export from the editor, or save a separate builder copy.')
    data = BuilderData.model_validate(draft.data)
    issues = export_issues(data)
    if issues: raise HTTPException(422, ' '.join(issues))
    content = to_content(data)
    try:
        if format == 'pdf':
            from .document_renderer import render_pdf
            output, _ = await asyncio.wait_for(render_pdf(content),timeout=65)
        else:
            from .studio_docx import measured_docx_bytes
            output = await measured_docx_bytes(content)
    except Exception:
        raise HTTPException(422, 'The exported file could not be validated. Simplify long content or try the other format.')
    mime = 'application/pdf' if format == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return Response(output, media_type=mime, headers={'Content-Disposition': f'attachment; filename="formiqo-resume.{format}"'})
