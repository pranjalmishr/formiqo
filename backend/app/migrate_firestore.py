"""Non-destructive SQL -> ordinary Firestore migration (no billing resources).

Run from backend with Google Application Default Credentials:
  python -m app.migrate_firestore --project nitre-d8cdd
  python -m app.migrate_firestore --project nitre-d8cdd --apply

Dry-run is the default. Existing conflicting Firestore records are never overwritten.
Expired records and orphaned children are excluded, with counts reported. Uploaded
binary files stay in private-storage; this command migrates structured records only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
import sqlite3

from google.cloud import firestore
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session as SQLSession

from .config import settings
from .db import Base,Resume,ConversionJob,now
from .firestore_store import FirestoreUnitOfWork,primary_key,record_values,encode_record,MAX_TRANSACTION_RECORDS


def source_records(source_url):
    engine=create_engine(source_url,hide_parameters=True)
    models={mapper.local_table.name:mapper.class_ for mapper in Base.registry.mappers}
    records=[];skipped=Counter()
    with SQLSession(engine) as db:
        resumes={r.id:r for r in db.scalars(select(Resume)) if r.expires_at>now()}
        jobs={r.id:r for r in db.scalars(select(ConversionJob)) if r.expires_at>now()}
        for table in Base.metadata.sorted_tables:
            model=models[table.name]
            for row in db.scalars(select(model)):
                if hasattr(row,'expires_at') and row.expires_at<=now():
                    skipped[table.name]+=1;continue
                if hasattr(row,'resume_id') and row.resume_id not in resumes:
                    skipped[table.name]+=1;continue
                if hasattr(row,'job_id') and row.job_id not in jobs:
                    skipped[table.name]+=1;continue
                if hasattr(row,'resume_id') and hasattr(row,'owner') and row.owner!=resumes[row.resume_id].owner:
                    raise RuntimeError('Source ownership mismatch; migration aborted without writing')
                if hasattr(row,'job_id') and hasattr(row,'owner') and row.owner!=jobs[row.job_id].owner:
                    raise RuntimeError('Source ownership mismatch; migration aborted without writing')
                encode_record(record_values(row))  # validate all sizes before writing anything
                records.append(row)
    engine.dispose()
    return records,skipped


def backup_sqlite(source_url):
    url=make_url(source_url)
    if not url.drivername.startswith('sqlite') or not url.database or url.database==':memory:':
        return None
    directory=settings.storage_dir/'migration-backups'
    directory.mkdir(parents=True,exist_ok=True,mode=0o700);directory.chmod(0o700)
    path=directory/('before-firestore-'+now().strftime('%Y%m%d-%H%M%S')+'.db')
    with sqlite3.connect(url.database) as source,sqlite3.connect(path) as output:
        source.backup(output)
    path.chmod(0o600)
    return path


def migrate(project,source_url,namespace='v1',apply=False,client=None):
    records,skipped=source_records(source_url)
    counts=Counter(type(row).__tablename__ for row in records)
    if len(records)>MAX_TRANSACTION_RECORDS:
        raise RuntimeError('Source exceeds the atomic migration guard. No data was written; migrate in explicitly reviewed batches.')
    client=client or firestore.Client(project=project)
    pending=0
    with FirestoreUnitOfWork(client,namespace) as target:
        identities=[(type(row),getattr(row,primary_key(type(row)))) for row in records]
        existing_records=target.get_many(identities)
        for row in records:
            identity=getattr(row,primary_key(type(row)))
            existing=existing_records[(type(row),identity)]
            if existing is not None:
                if record_values(existing)!=record_values(row):
                    raise RuntimeError('A target record differs from the source; no existing data was overwritten')
            else:
                target.add(row);pending+=1
        result={'source_records':len(records),'by_collection':dict(counts),'excluded_expired_or_orphaned':dict(skipped),'new_records':pending,'applied':False}
        if apply:
            backup=backup_sqlite(source_url)
            target.commit()
            result['applied']=True
            result['local_backup_created']=backup is not None
            # Verify all IDs in a fresh unit of work, not the source identity map.
            with FirestoreUnitOfWork(client,namespace) as verify:
                verified=verify.get_many(identities)
                for row in records:
                    item=verified[(type(row),getattr(row,primary_key(type(row))))]
                    if item is None or record_values(item)!=record_values(row):
                        raise RuntimeError('Read-back verification failed; source database and local backup are intact')
            result['verified_records']=len(records)
            target.root.set({'application':'Formiqo','schema_version':1,'data_store':'firestore','billing_policy':'no billing account','migration_verified_at':now()},merge=True)
        return result


def main():
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--source',default=settings.database_url)
    parser.add_argument('--namespace',default='v1')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    result=migrate(args.project,args.source,args.namespace,args.apply)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
