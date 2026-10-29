"""Private Vercel Blob storage, with /tmp as a disposable per-instance cache.

Firestore holds structured data only. Binaries never become public blobs and are
only hydrated after the existing route has checked owner and expiry. No bucket
listing is used for ordinary reads: the server derives each exact object path.
Local mode preserves the original Docker/development file behavior.
"""
from pathlib import Path
import mimetypes
import os
import tempfile
from fastapi import HTTPException
from .config import settings


def enabled():return settings.file_storage_backend=='vercel_blob'


def object_key(path):
    path=Path(path).resolve();root=settings.storage_dir.resolve()
    try:relative=path.relative_to(root)
    except ValueError:raise ValueError('File path is outside private storage') from None
    if not relative.parts:raise ValueError('Cannot access the storage root as an object')
    return 'formiqo/'+settings.firebase_namespace+'/'+relative.as_posix()


def _unavailable(exc):
    # Do not echo SDK/token-bearing exceptions into API responses or logs.
    raise HTTPException(503,'Private file storage is unavailable or its Hobby allowance is exhausted. Retry later; the file was not made public.') from None


def persist(path):
    path=Path(path)
    if not enabled():return
    from vercel.blob.sync import put_blob
    try:
        with path.open('rb') as stream:
            put_blob(object_key(path),stream,access='private',content_length=path.stat().st_size,content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',add_random_suffix=False,allow_overwrite=True)
    except Exception as exc:_unavailable(exc)


def hydrate(path):
    path=Path(path)
    if path.is_file() or not enabled():return path.is_file()
    from vercel.blob.sync import stream_blob
    from vercel.blob import BlobNotFoundError
    temporary=None
    try:
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with stream_blob(object_key(path),access='private') as download:
            fd,name=tempfile.mkstemp(prefix='.hydrating-',dir=path.parent);temporary=Path(name)
            with os.fdopen(fd,'wb') as stream:
                total=0
                for chunk in download:
                    total+=len(chunk)
                    if total>150*1024*1024:raise ValueError('File exceeds private storage read limit')
                    stream.write(chunk)
            temporary.chmod(0o600);temporary.replace(path);temporary=None
        return True
    except BlobNotFoundError:return False
    except Exception as exc:_unavailable(exc)
    finally:
        if temporary:temporary.unlink(missing_ok=True)


def response(path,media_type,filename=None,disposition='inline'):
    """Stream private files without keeping a large download cache in /tmp."""
    from fastapi.responses import FileResponse,StreamingResponse
    from urllib.parse import quote
    path=Path(path)
    if not enabled():
        return FileResponse(path,media_type=media_type,filename=filename,content_disposition_type=disposition,headers={'Cache-Control':'private, no-store'})
    from vercel.blob.sync import stream_blob
    from vercel.blob import BlobNotFoundError
    context=stream_blob(object_key(path),access='private')
    try:download=context.__enter__()
    except BlobNotFoundError:raise HTTPException(410,'The private file is no longer available.') from None
    except Exception as exc:_unavailable(exc)
    def chunks():
        try:yield from download
        finally:context.__exit__(None,None,None)
    headers={'Cache-Control':'private, no-store','Content-Disposition':disposition+"; filename*=utf-8''"+quote(filename or path.name)}
    return StreamingResponse(chunks(),media_type=media_type,headers=headers)


def exists(path):
    path=Path(path)
    if not enabled():return path.is_file()
    from vercel.blob.sync import head_blob
    from vercel.blob import BlobNotFoundError
    try:head_blob(object_key(path));return True
    except BlobNotFoundError:return False
    except Exception as exc:_unavailable(exc)


def remove(path):
    path=Path(path)
    if enabled():
        from vercel.blob.sync import delete_blob
        from vercel.blob import BlobNotFoundError
        try:delete_blob(object_key(path))
        except BlobNotFoundError:pass
        except Exception as exc:_unavailable(exc)
    path.unlink(missing_ok=True)


def remove_tree(path):
    path=Path(path)
    if enabled():
        from vercel.blob.sync import query_blobs,delete_blob
        try:
            prefix=object_key(path).rstrip('/')+'/'
            urls=[blob.url for blob in query_blobs(prefix=prefix)]
            if urls:delete_blob(urls)
        except Exception as exc:_unavailable(exc)
    import shutil
    shutil.rmtree(path,ignore_errors=True)


def inputs(job):
    from .converter_api import job_dir
    (job_dir(job.id)/'outputs').mkdir(parents=True,exist_ok=True,mode=0o700)
    for entry in job.inputs:
        name=entry['path']
        if Path(name).name!=name:raise ValueError('Invalid input filename')
        path=job_dir(job.id)/'inputs'/name
        if not hydrate(path):raise HTTPException(410,'Prepared input has expired or was removed. Upload it again.')


def persist_inputs(job):
    from .converter_api import job_dir
    for entry in job.inputs:persist(job_dir(job.id)/'inputs'/entry['path'])


def persist_outputs(job_id,outputs):
    from .converter_api import job_dir
    for item in outputs:
        name=item['filename']
        if Path(name).name!=name:raise ValueError('Invalid output filename')
        persist(job_dir(job_id)/'outputs'/name)
