"""Copy existing active private files into the linked Vercel Blob store.

Dry-run by default. Only files referenced by active database records are eligible;
never uploads .env, credentials, database backups, logs or arbitrary directories.
Set BLOB_READ_WRITE_TOKEN in the process environment, not in source or CLI flags.
"""
import argparse
import hashlib
from pathlib import Path
from .config import settings
from .db import Session,Resume,SourceDocument,ConversionJob,now
from .persistence import find
from . import durable_files


def candidates():
    paths=[];missing=0
    with Session() as db:
        active_resumes={resume.id:resume for resume in find(db,Resume,[('expires_at','>',now())])}
        for source in find(db,SourceDocument):
            resume=active_resumes.get(source.resume_id)
            if not resume or resume.expires_at<=now():continue
            paths.append(settings.storage_dir/'originals'/f'{source.resume_id}.{source.format}')
        for job in find(db,ConversionJob,[('expires_at','>',now())]):
            if job.status=='completed':
                for output in job.outputs:
                    name=output['filename']
                    if Path(name).name!=name:raise ValueError('Unsafe output filename')
                    paths.append(settings.storage_dir/'jobs'/job.id/'outputs'/name)
            if job.status=='prepared':
                for entry in job.inputs:
                    name=entry['path']
                    if Path(name).name!=name:raise ValueError('Unsafe input filename')
                    paths.append(settings.storage_dir/'jobs'/job.id/'inputs'/name)
    available=[]
    for path in dict.fromkeys(paths):
        durable_files.object_key(path)  # validates every path before any write
        if path.is_file():available.append(path)
        else:missing+=1
    return available,missing


def migrate(apply=False):
    from vercel.blob.sync import get_blob,head_blob
    from vercel.blob import BlobNotFoundError
    paths,missing=candidates();total=sum(p.stat().st_size for p in paths)
    if total>512*1024*1024:raise ValueError('Migration exceeds the conservative Hobby storage guard; review file retention first')
    result={'eligible_files':len(paths),'bytes':total,'unavailable_local_files':missing,'applied':False}
    if not apply:return result
    old=settings.file_storage_backend;settings.file_storage_backend='vercel_blob'
    try:
        for path in paths:
            key=durable_files.object_key(path);source=path.read_bytes();digest=hashlib.sha256(source).digest()
            try:
                head_blob(key)
                current=get_blob(key,access='private').body
                if hashlib.sha256(current).digest()!=digest:raise RuntimeError('Existing cloud file differs; migration stopped without overwriting it')
            except BlobNotFoundError:durable_files.persist(path)
            downloaded=get_blob(key,access='private').body
            if hashlib.sha256(downloaded).digest()!=digest:raise RuntimeError('Private file read-back verification failed')
        result['applied']=True;result['verified_files']=len(paths)
    finally:settings.file_storage_backend=old
    return result


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true')
    print(json.dumps(migrate(parser.parse_args().apply),indent=2))
