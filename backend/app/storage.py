import hashlib
import secrets
import time
import threading
import zipfile
from collections import defaultdict, deque
from pathlib import Path
from fastapi import HTTPException, Request, Response, UploadFile
from .config import settings

_lock = threading.Lock()
_rates = defaultdict(deque)
MIMES = {'pdf': {'application/pdf'}, 'docx': {'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/zip'}, 'txt': {'text/plain'}}


def initialize_storage():
    settings.storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.storage_dir.chmod(0o700)


def owner(request: Request, response: Response):
    from .auth import current_user, user_owner
    user = current_user(request)
    if user:
        return user_owner(user)
    if not settings.guest_allowed and request.url.path != '/api/config':
        raise HTTPException(401, 'Sign in to use this workspace; guest access is disabled.')
    # A random HttpOnly guest capability, never an owner supplied by the browser.
    token = request.cookies.get('resumeai_session', '')
    if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        token = secrets.token_hex(32)
        response.set_cookie('resumeai_session', token, httponly=True, secure=settings.secure_cookie, samesite='strict', max_age=settings.retention_hours * 3600, path='/')
    return hashlib.sha256(token.encode()).hexdigest()


def rate_limit(request: Request, bucket: str, limit: int | None = None):
    # In-memory limiter is for the documented single API instance only.
    key = (request.client.host if request.client else 'unknown', bucket)
    with _lock:
        ticks = _rates[key]
        t = time.monotonic()
        while ticks and ticks[0] < t - 3600:
            ticks.popleft()
        if len(ticks) >= (settings.guest_limit_per_hour if limit is None else limit):
            raise HTTPException(429, 'Hourly usage limit reached. Please try again later.', headers={'Retry-After': '3600'})
        ticks.append(t)
        for old in list(_rates):
            if old != key and (not _rates[old] or _rates[old][-1] < t - 3600):
                del _rates[old]


def safe_filename(name: str):
    name = name.replace('\\', '/').split('/')[-1]
    name = ''.join(c for c in name if c.isprintable() and c not in '<>:"|?*').strip('. ')
    return (name or 'resume')[:180]


async def store_upload(file: UploadFile, identifier: str):
    name = safe_filename(file.filename or '')
    ext = Path(name).suffix.lower().lstrip('.')
    if ext not in MIMES:
        raise HTTPException(415, 'Upload a PDF, DOCX, or TXT resume. Legacy DOC is not supported.')
    if (file.content_type or '').split(';')[0] not in MIMES[ext]:
        raise HTTPException(415, 'The file MIME type does not match an accepted resume format.')
    path = settings.storage_dir / f'{identifier}.{ext}'
    size = 0
    try:
        with path.open('xb') as output:
            path.chmod(0o600)
            while chunk := await file.read(65536):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, f'File exceeds {settings.max_upload_mb} MB.')
                output.write(chunk)
        if size == 0:
            raise HTTPException(422, 'The uploaded document is empty.')
        validate_signature(path, ext)
    except OSError:
        path.unlink(missing_ok=True)
        raise HTTPException(507, 'Private upload storage is unavailable. Check disk space and permissions, then retry.')
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return path, name, ext


def validate_signature(path: Path, ext: str):
    with path.open('rb') as stream:
        start = stream.read(1024)
    if ext == 'pdf' and not start.startswith(b'%PDF-'):
        raise HTTPException(422, 'Invalid or corrupted PDF signature.')
    if ext == 'docx':
        try:
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
                if len(infos) > 2000 or sum(i.file_size for i in infos) > 40 * 1024 * 1024 or any(i.file_size > 15 * 1024 * 1024 or i.file_size / max(i.compress_size, 1) > 200 for i in infos):
                    raise ValueError('Expanded document is too large')
                names = {i.filename for i in infos}
                if '[Content_Types].xml' not in names or 'word/document.xml' not in names or any('vbaproject' in n.lower() for n in names):
                    raise ValueError('Not a macro-free DOCX document')
                if any(n.startswith('/') or '..' in Path(n).parts for n in names):
                    raise ValueError('Unsafe archive path')
        except (zipfile.BadZipFile, ValueError) as exc:
            raise HTTPException(422, f'Invalid DOCX: {exc}') from exc
    if ext == 'txt':
        try:
            content = path.read_text(encoding='utf-8-sig')
            if '\x00' in content or any(ord(c) < 32 and c not in '\n\r\t' for c in content):
                raise ValueError('Binary content detected')
        except (UnicodeError, ValueError) as exc:
            raise HTTPException(422, 'TXT must contain UTF-8 plain text, not binary data.') from exc


def remove_source(identifier: str, include_original: bool = False):
    from .durable_files import remove
    for ext in MIMES:
        (settings.storage_dir / f'{identifier}.{ext}').unlink(missing_ok=True)
        if include_original:
            remove(settings.storage_dir / 'originals' / f'{identifier}.{ext}')
