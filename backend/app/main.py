import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import shutil
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import IntegrityError
from fastapi.responses import JSONResponse
from .persistence import find, first, remove_where, ping
from sqlalchemy.orm import Session as DBSession
from .config import settings
from .db import Session, Resume, Analysis, ResumeVersion, EditorDraft, EditorVersion, BuilderDraft, SourceDocument, init_db, get_db, now, uid
from .storage import owner, rate_limit, initialize_storage, store_upload, remove_source
from .schemas import AnalyzeRequest, DraftPatch, CompareRequest
from .scoring import analyze
from .ai import evaluate,attach_semantic_diagnostics
from .middleware import RequestSizeLimit
from .auth import retention_expiry
from .processing import native_slots

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='resume-extraction')
_slots = native_slots
_pending = set()
_cleanup_error = None
_cleanup_success = None


def expire_records():
    from .converter_api import cleanup_jobs
    cleanup_jobs()
    with Session() as db:
        expired = find(db, Resume, [('expires_at','<',now())])
        for resume in expired:
            remove_source(resume.id, include_original=True)
            for model in [SourceDocument,Analysis,ResumeVersion,EditorVersion,EditorDraft,BuilderDraft]:
                remove_where(db,model,[('resume_id','==',resume.id)])
            db.delete(resume)
        db.commit()
    # Interrupted requests can leave sources before a DB row was created.
    import time
    for path in settings.storage_dir.iterdir():
        if path.is_file() and path.stat().st_mtime < time.time() - settings.retention_hours * 3600:
            path.unlink(missing_ok=True)
    scratch_root=settings.storage_dir/'scratch'
    if scratch_root.exists():
        for path in scratch_root.iterdir():
            if path.is_dir() and path.stat().st_mtime < time.time() - settings.retention_hours*3600:
                shutil.rmtree(path,ignore_errors=True)


async def janitor():
    global _cleanup_error, _cleanup_success
    while True:
        try:
            await asyncio.to_thread(expire_records)
            _cleanup_error = None
            _cleanup_success = now().isoformat()
        except Exception as exc:
            _cleanup_error = type(exc).__name__
            logging.getLogger('formiqo').error('Retention cleanup failed (%s); retrying in 60 seconds.', _cleanup_error)
        # Avoid continuous free-tier database reads just for retention cleanup.
        # Ownership/expiry is still checked on every request immediately.
        await asyncio.sleep(900 if settings.database_backend=='firestore' else 60)


@asynccontextmanager
async def lifespan(app):
    initialize_storage()
    init_db()
    from .converter_api import recover_jobs
    recover_jobs()
    with Session() as db:
        for r in find(db,Resume,[('status','in',['queued','processing'])]):
            r.status = 'failed'
            r.error = 'Processing was interrupted by a server restart. Please upload again.'
            remove_source(r.id)
        db.commit()
    task = asyncio.create_task(janitor())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title='Formiqo — One Platform, Every Document', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.allowed_origin], allow_credentials=True, allow_methods=['GET', 'POST', 'PATCH', 'DELETE'], allow_headers=['Content-Type'])


@app.exception_handler(IntegrityError)
async def persistence_conflict(request, exc):
    return JSONResponse({'detail':'A conflicting record already exists. Reload or sign in before retrying.'},status_code=409)


@app.middleware('http')
async def security(request: Request, call_next):
    origin = request.headers.get('origin')
    same_origin = str(request.base_url).rstrip('/')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin not in (settings.allowed_origin, same_origin):
        return JSONResponse({'detail': 'Untrusted request origin.'}, status_code=403)
    request_id = uuid.uuid4().hex
    try:
        response = await call_next(request)
    except Exception as exc:
        logging.getLogger('formiqo').error('request_failed id=%s method=%s path=%s class=%s', request_id, request.method, request.url.path, type(exc).__name__)
        response = JSONResponse({'detail': 'Unexpected server error. Retry safely or report reference '+request_id+'.', 'request_id': request_id}, status_code=500)
    response.headers['X-Request-ID'] = request_id
    logging.getLogger('formiqo').info('request id=%s method=%s path=%s status=%s', request_id, request.method, request.url.path, response.status_code)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.url.path.startswith('/api/') and not request.url.path.startswith('/api/studio/fonts/') and request.url.path != '/api/studio/runtime.js':
        response.headers['Cache-Control'] = 'no-store'
    return response


app.add_middleware(RequestSizeLimit)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=settings.allowed_hosts)


def require_resume(db, identifier, owner_id):
    record = db.get(Resume, identifier)
    if not record or record.owner != owner_id or record.expires_at.replace(tzinfo=now().tzinfo) < now():
        raise HTTPException(404, 'Resume not found or expired.')
    return record


def require_analysis(db, identifier, owner_id):
    record = db.get(Analysis, identifier)
    if not record or record.owner != owner_id:
        raise HTTPException(404, 'Analysis not found or expired.')
    require_resume(db, record.resume_id, owner_id)
    return record


def serialize_resume(r, full=True):
    result = {'id': r.id, 'filename': r.filename, 'original_format': r.original_format, 'status': r.status, 'error': r.error, 'created_at': r.created_at.isoformat(), 'updated_at': r.updated_at.isoformat(), 'expires_at': r.expires_at.isoformat()}
    if full:
        result.update(text=r.text, original_text=r.original_text, extraction=r.extraction)
    return result


def run_worker(path, ext):
    scratch=settings.storage_dir/'scratch'/path.stem
    scratch.mkdir(parents=True,exist_ok=True,mode=0o700)
    process = subprocess.Popen([sys.executable, '-m', 'app.worker', str(path.resolve()), ext], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env={**os.environ, 'OMP_THREAD_LIMIT': '1', 'TMPDIR': str(scratch.resolve())})
    try:
        stdout, _ = process.communicate(timeout=settings.extraction_timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return {'error': 'Document processing timed out. Try a smaller document or a selectable-text export.'}
    finally:
        shutil.rmtree(scratch,ignore_errors=True)
    try:
        result = json.loads(stdout)
        if process.returncode != 0 and 'error' not in result:
            return {'error': 'Document could not be processed safely.'}
        return result
    except (ValueError, UnicodeError):
        return {'error': 'The document parser failed safely. Try re-exporting your document.'}


async def process_document(identifier, path, ext):
    try:
        async with _slots:
            with Session() as db:
                r = db.get(Resume, identifier)
                if not r:
                    return
                r.status = 'processing'
                db.commit()
            result = await asyncio.get_running_loop().run_in_executor(_pool, run_worker, path, ext)
            with Session() as db:
                r = db.get(Resume, identifier)
                if r:
                    if result.get('error'):
                        r.status, r.error = 'failed', result['error']
                    else:
                        r.text = r.original_text = result['text']
                        r.extraction = result['extraction']
                        r.status = 'ready'
                        db.add(ResumeVersion(resume_id=r.id, text=r.text))
                    db.commit()
    except Exception:
        with Session() as db:
            r = db.get(Resume, identifier)
            if r:
                r.status, r.error = 'failed', 'Processing failed. Please upload again.'
                db.commit()
    finally:
        remove_source(identifier)
        _pending.discard(identifier)


@app.get('/api/health')
def health(db: DBSession = Depends(get_db)):
    ping(db)
    return {'status': 'degraded' if _cleanup_error else 'ok', 'product': 'Formiqo', 'database_backend':settings.database_backend,'cleanup_last_success': _cleanup_success, 'cleanup_error': _cleanup_error, 'modules': ['ats-checker', 'resume-editor', 'resume-builder', 'document-converter', 'document-library', 'accounts', 'job-matcher', 'resume-assistant']}


@app.get('/api/config')
def configuration(response: Response, owner_id=Depends(owner)):
    import shutil
    return {'max_upload_mb': settings.max_upload_mb, 'max_pages': settings.max_pages, 'retention_hours': settings.retention_hours, 'account_retention_days': settings.account_retention_days, 'guest_allowed': settings.guest_allowed, 'guest_limit_per_hour': settings.guest_limit_per_hour, 'ai_available': bool(settings.llm_api_key), 'ai_provider': settings.llm_base_url, 'ai_model': settings.llm_model, 'ocr_available': bool(shutil.which('tesseract')), 'weights': settings.scoring_weights, 'accounts_enabled': settings.accounts_enabled, 'email_available': bool(settings.smtp_host),'database_backend':settings.database_backend,'firebase_project_id':settings.firebase_project_id if settings.database_backend=='firestore' else None,'binary_storage':'private backend files'}


@app.post('/api/resumes/upload', status_code=202)
async def upload(request: Request, background: BackgroundTasks, file: UploadFile = File(...), owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    rate_limit(request, 'uploads')
    if len(_pending) >= 20:
        raise HTTPException(503, 'The extraction queue is full. Please retry shortly.')
    identifier = uid()
    _pending.add(identifier)
    try:
        path, filename, ext = await store_upload(file, identifier)
    except Exception:
        _pending.discard(identifier)
        raise
    try:
        resume = Resume(id=identifier, owner=owner_id, filename=filename, original_format=ext, expires_at=retention_expiry(owner_id))
        originals=settings.storage_dir/'originals'
        originals.mkdir(parents=True,exist_ok=True,mode=0o700)
        original=originals/f'{identifier}.{ext}'
        shutil.copyfile(path,original);original.chmod(0o600)
        db.add(resume);db.flush()
        db.add(SourceDocument(resume_id=identifier,format=ext,filename=filename,size=path.stat().st_size))
        db.commit()
    except Exception:
        remove_source(identifier, include_original=True)
        _pending.discard(identifier)
        raise HTTPException(503, 'Storage is unavailable. Please try again.')
    _pending.add(identifier)
    background.add_task(process_document, identifier, path, ext)
    return serialize_resume(resume)


@app.get('/api/resumes')
def list_resumes(offset: int = 0, limit: int = 50, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, 'Invalid pagination range.')
    records = find(db,Resume,[('owner','==',owner_id),('expires_at','>',now())],[('updated_at','desc')],limit=limit,offset=offset)
    items = []
    for r in records:
        item = serialize_resume(r, False)
        latest = first(db,Analysis,[('resume_id','==',r.id)],[('created_at','desc')])
        item['latest_analysis_id'] = latest.id if latest else None
        item['latest_score'] = latest.overall_score if latest else None
        item['has_builder'] = db.get(BuilderDraft, r.id) is not None
        items.append(item)
    return {'items': items, 'offset': offset, 'limit': limit}


@app.get('/api/resumes/{identifier}')
def get_resume(identifier: str, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    return serialize_resume(require_resume(db, identifier, owner_id))


@app.patch('/api/resumes/{identifier}')
def save_resume(identifier: str, data: DraftPatch, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    r = require_resume(db, identifier, owner_id)
    if r.status != 'ready':
        raise HTTPException(409, 'Wait for extraction to finish before editing.')
    if not data.text.strip():
        raise HTTPException(422, 'Resume text cannot be empty.')
    if r.text != data.text:
        r.text = data.text
        db.add(ResumeVersion(resume_id=r.id, text=r.text))
        db.commit()
    return serialize_resume(r)


@app.get('/api/resumes/{identifier}/versions')
def versions(identifier: str, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    require_resume(db, identifier, owner_id)
    records = find(db,ResumeVersion,[('resume_id','==',identifier)],[('created_at','desc')],limit=20)
    return {'items': [{'id': v.id, 'text': v.text, 'created_at': v.created_at.isoformat()} for v in records]}


@app.get('/api/resumes/{identifier}/download')
def download_draft(identifier: str, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    r = require_resume(db, identifier, owner_id)
    if r.status != 'ready':
        raise HTTPException(409, 'A readable draft is not available yet.')
    return Response(r.text, media_type='text/plain; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="resume-draft.txt"'})


@app.delete('/api/resumes/{identifier}', status_code=204)
def delete_resume(identifier: str, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    r = require_resume(db, identifier, owner_id)
    for model in [Analysis,ResumeVersion,EditorVersion,EditorDraft,BuilderDraft,SourceDocument]:
        remove_where(db,model,[('resume_id','==',identifier)])
    db.delete(r)
    db.commit()
    remove_source(identifier, include_original=True)
    return Response(status_code=204)


@app.post('/api/ats/analyze', status_code=201)
@app.post('/api/ats/reanalyze', status_code=201)
async def analyze_resume(data: AnalyzeRequest, request: Request, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    rate_limit(request, 'analyses')
    r = require_resume(db, data.resume_id, owner_id)
    if r.status != 'ready':
        raise HTTPException(409, 'Text extraction is not ready. Retry after processing finishes.')
    if data.mode == 'job' and len(data.job_description.strip()) < 40:
        raise HTTPException(422, 'Job-specific analysis requires a job description of at least 40 characters.')
    if len(data.text.strip()) < 20:
        raise HTTPException(422, 'Please provide at least 20 characters of readable resume text.')
    jd = data.job_description if data.mode == 'job' else ''
    result = await asyncio.to_thread(analyze, data.text, r.extraction, jd, data.mode)
    result['semantic_observations'] = []
    result['ai_notice'] = 'External AI was not used. Local rubric only.'
    if data.ai_consent:
        observations, notice = await evaluate(data.text, jd)
        result['semantic_observations'] = observations or []
        result['ai_notice'] = notice
        attach_semantic_diagnostics(result,result['semantic_observations'])
    # Store inputs with the result so comparisons never compare incompatible rubrics/JDs.
    result['context'] = {'job_description': jd, 'job_title': data.job_title, 'company': data.company, 'industry': data.industry}
    if r.text != data.text:
        r.text = data.text
        db.add(ResumeVersion(resume_id=r.id, text=r.text))
    record = Analysis(owner=owner_id, resume_id=r.id, overall_score=result['overall_score'], result=result, scoring_version=result['scoring_version'])
    db.add(record)
    db.commit()
    return {**result, 'id': record.id, 'resume_id': r.id, 'filename': r.filename, 'created_at': record.created_at.isoformat()}


@app.get('/api/ats/results/{identifier}')
def get_analysis(identifier: str, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    a = require_analysis(db, identifier, owner_id)
    r = require_resume(db, a.resume_id, owner_id)
    return {**a.result, 'id': a.id, 'resume_id': a.resume_id, 'filename': r.filename, 'created_at': a.created_at.isoformat()}


@app.post('/api/ats/compare')
def compare(data: CompareRequest, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    original = require_analysis(db, data.original_id, owner_id)
    updated = require_analysis(db, data.updated_id, owner_id)
    if original.resume_id != updated.resume_id or original.scoring_version != updated.scoring_version or original.result['context'] != updated.result['context'] or original.result['mode'] != updated.result['mode']:
        raise HTTPException(409, 'Compare the same resume using the same methodology and analysis context.')
    before={(f['category'],f['title']) for f in original.result.get('findings',[])}
    after={(f['category'],f['title']) for f in updated.result.get('findings',[])}
    return {'original': original.overall_score, 'updated': updated.overall_score, 'change': updated.overall_score - original.overall_score, 'categories': [{'key': a['key'], 'change': b['score'] - a['score']} for a, b in zip(original.result['categories'], updated.result['categories'])], 'resolved':sorted(title for _,title in before-after), 'remaining':sorted(title for _,title in after), 'introduced':sorted(title for _,title in after-before)}


from .editor_api import router as editor_router
app.include_router(editor_router)
from .builder_api import router as builder_router
app.include_router(builder_router)
from .auth import router as auth_router
from .converter_api import router as converter_router
from .library import router as library_router
app.include_router(auth_router)
app.include_router(converter_router)
app.include_router(library_router)
from .intelligence import router as intelligence_router
app.include_router(intelligence_router)
from .activity import router as activity_router
app.include_router(activity_router)
from .studio_api import router as studio_router
app.include_router(studio_router)
from .import_api import router as import_router
app.include_router(import_router)
from .tools_api import router as tools_router
app.include_router(tools_router)

from .records_api import router as records_router
app.include_router(records_router)
