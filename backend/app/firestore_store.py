"""Native Cloud Firestore primary persistence, compatible with the free Spark plan.

All records live under formiqo/<namespace>/formiqo_<entity>/<id>. This module never
runs SQL, creates a billing account, stores uploaded binaries, or silently falls
back to SQLite. Existing model classes are reused as typed record containers.

The unit of work batches related edits in a Firestore transaction. Update-time
preconditions preserve revision conflicts, single-use tokens and unique emails.
Reads use an indexed owner/parent/equality anchor; remaining filtering/sorting is
performed only on that candidate set, avoiding a collection-wide read per filter.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import re
import zlib

from fastapi import HTTPException
from sqlalchemy import inspect as model_inspect
from sqlalchemy.exc import IntegrityError

MAX_DOCUMENT_BYTES = 900_000  # leave headroom below Firestore's 1 MiB document limit
MAX_EXPANDED_BYTES = 4_000_000
MAX_TRANSACTION_RECORDS = 400  # conservative application bound, not a Firebase quota claim
MAX_TRANSACTION_BYTES = 8_000_000  # headroom for metadata below Firestore's 10 MiB request limit
MAX_QUERY_CANDIDATES = 5000


def record_values(record):
    return {column.key:deepcopy(getattr(record,column.key)) for column in model_inspect(type(record)).columns}


def primary_key(model):
    keys = list(model_inspect(model).primary_key)
    if len(keys) != 1:
        raise ValueError('Firestore records require one primary key')
    return keys[0].key


def json_default(value):
    if isinstance(value,datetime):
        return {'__formiqo_datetime__':value.isoformat()}
    raise TypeError('Unsupported record value: '+type(value).__name__)


def json_hook(value):
    if set(value)=={'__formiqo_datetime__'}:
        return datetime.fromisoformat(value['__formiqo_datetime__'])
    return value


def encode_record(values):
    """Normal fields remain readable in the console. Large records use a bounded
    compressed payload while retaining scalar fields needed by indexed queries."""
    raw=json.dumps(values,default=json_default,ensure_ascii=False,separators=(',',':')).encode()
    if len(raw)>MAX_EXPANDED_BYTES:
        raise HTTPException(413,'This record exceeds the Firestore data limit. Shorten the document before saving.')
    if len(raw)<=MAX_DOCUMENT_BYTES:
        return values
    packed=zlib.compress(raw,level=6)
    scalars={k:v for k,v in values.items() if v is None or isinstance(v,(bool,int,float,datetime)) or isinstance(v,str) and len(v.encode())<2048}
    scalars['_formiqo_payload_zlib']=packed
    if len(packed)+sum(len(str(v).encode()) for k,v in scalars.items() if k!='_formiqo_payload_zlib')>MAX_DOCUMENT_BYTES:
        raise HTTPException(413,'The record cannot fit in a Firestore document. No content was truncated.')
    return scalars


def decode_record(data):
    if '_formiqo_payload_zlib' not in data:
        return data
    decoder=zlib.decompressobj()
    raw=decoder.decompress(data['_formiqo_payload_zlib'],MAX_EXPANDED_BYTES+1)
    if len(raw)>MAX_EXPANDED_BYTES or not decoder.eof:
        raise ValueError('Firestore record exceeds the decompression limit')
    return json.loads(raw,object_hook=json_hook)


@lru_cache(maxsize=8)
def client_for(project, database='(default)', credentials_file=None):
    from google.cloud import firestore
    if not project:
        raise RuntimeError('FIREBASE_PROJECT_ID is required for Firestore; no SQLite fallback is performed')
    if credentials_file:
        import google.auth
        # Preserve the scopes granted to the existing ADC/OAuth credential. The
        # installed Firebase CLI OAuth client does not register a separate datastore scope.
        credentials,_=google.auth.load_credentials_from_file(str(credentials_file))
        return firestore.Client(project=project,database=database,credentials=credentials)
    import os
    if os.environ.get('GCP_WIF_PROVIDER'):
        from .vercel_identity import credentials
        return firestore.Client(project=project,database=database,credentials=credentials())
    return firestore.Client(project=project,database=database)


def matches(record,filters):
    for field,operator,value in filters:
        current=getattr(record,field)
        if isinstance(current,datetime) and current.tzinfo is None:
            current=current.replace(tzinfo=timezone.utc)
        if operator=='==' and current!=value:return False
        if operator=='!=' and current==value:return False
        if operator=='in' and current not in value:return False
        if operator=='>' and not(current is not None and current>value):return False
        if operator=='>=' and not(current is not None and current>=value):return False
        if operator=='<' and not(current is not None and current<value):return False
        if operator=='<=' and not(current is not None and current<=value):return False
    return True


class FirestoreUnitOfWork:
    is_firestore=True

    def __init__(self,client,namespace='v1'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',namespace):
            raise ValueError('Invalid FIREBASE_NAMESPACE')
        self.client=client
        self.root=client.collection('formiqo').document(namespace)
        self.objects={}
        self.originals={}
        self.versions={}
        self.new=set()
        self.deleted=set()
        self.closed=False

    def __enter__(self):return self

    def __exit__(self,exc_type,exc,tb):
        self.close()
        return False

    def close(self):
        self.rollback()
        self.closed=True

    def collection(self,model):
        return self.root.collection('formiqo_'+model.__tablename__)

    def reference(self,model,key):
        if not isinstance(key,str) or not key or '/' in key or len(key)>256:
            raise ValueError('Invalid record identifier')
        return self.collection(model).document(key)

    def _materialize(self,model,snapshot):
        key=snapshot.id;identity=(model,key)
        if identity in self.deleted:return None
        if identity in self.objects:return self.objects[identity]
        if not snapshot.exists:return None
        values=decode_record(snapshot.to_dict())
        columns={column.key for column in model_inspect(model).columns}
        record=model(**{key:value for key,value in values.items() if key in columns})
        self.objects[identity]=record;self.originals[identity]=record_values(record);self.versions[identity]=snapshot.update_time
        return record

    def get(self,model,key):
        identity=(model,key)
        if identity in self.deleted:return None
        if identity in self.objects:return self.objects[identity]
        return self._materialize(model,self.reference(model,key).get(timeout=20,retry=None))

    def get_many(self,identities):
        """BatchGet reduces network round trips during migration and verification."""
        refs={self.reference(*identity).path:identity for identity in identities}
        result={identity:None for identity in identities}
        if not refs:return result
        for snapshot in self.client.get_all([self.client.document(path) for path in refs],timeout=25,retry=None):
            identity=refs[snapshot.reference.path]
            result[identity]=self._materialize(identity[0],snapshot)
        return result

    def _defaults(self,record):
        for column in model_inspect(type(record)).columns:
            if getattr(record,column.key,None) is None and column.default is not None:
                default=column.default.arg
                setattr(record,column.key,default(None) if callable(default) else deepcopy(default))

    def add(self,record):
        self._defaults(record)
        model=type(record);key=getattr(record,primary_key(model));identity=(model,key)
        if identity not in self.objects:
            self.objects[identity]=record;self.new.add(identity)
        self.deleted.discard(identity)

    def add_all(self,records):
        for record in records:self.add(record)

    def delete(self,record):
        model=type(record);identity=(model,getattr(record,primary_key(model)))
        self.objects.setdefault(identity,record)
        self.deleted.add(identity)

    def find(self,model,filters=(),order=(),limit=None,offset=0):
        from google.cloud.firestore_v1.base_query import FieldFilter
        key=primary_key(model)
        id_filter=next((value for field,op,value in filters if field==key and op=='=='),None)
        if id_filter is not None:
            item=self.get(model,id_filter);candidates=[item] if item is not None else []
        else:
            # Prefer a narrow equality anchor. Date/expiry and other conditions are
            # checked afterwards so no cross-field composite index is required.
            priority=('resume_id','job_id','user_id','owner','email','token_hash')
            anchor=next(((field,op,value) for field in priority for f,op,value in filters if f==field and op=='=='),None)
            if anchor is None:anchor=next((item for item in filters if item[1] in ('==','in','<','>','<=','>=')),None)
            query=self.collection(model)
            if anchor:
                field,op,value=anchor;query=query.where(filter=FieldFilter(field,op,value))
            snapshots=list(query.limit(MAX_QUERY_CANDIDATES+1).stream(timeout=25,retry=None))
            if len(snapshots)>MAX_QUERY_CANDIDATES:
                raise HTTPException(503,'This query exceeds the free-tier application read guard. Narrow the request or archive older records.')
            candidates=[item for snapshot in snapshots if (item:=self._materialize(model,snapshot)) is not None]
            # Match SQL's transaction visibility for staged creates and deletes.
            seen={getattr(item,key) for item in candidates}
            candidates += [item for (kind,identifier),item in self.objects.items() if kind is model and identifier not in seen and (kind,identifier) not in self.deleted and (kind,identifier) in self.new]
        candidates=[item for item in candidates if matches(item,filters)]
        for field,direction in reversed(order):
            candidates.sort(key=lambda item:(getattr(item,field) is not None,getattr(item,field)),reverse=direction=='desc')
        return candidates[offset:offset+limit] if limit is not None else candidates[offset:]

    def remove_where(self,model,filters):
        records=self.find(model,filters)
        for record in records:self.delete(record)
        return len(records)

    def change_where(self,model,filters,values):
        records=self.find(model,filters)
        for record in records:
            for key,value in values.items():setattr(record,key,deepcopy(value))
        return len(records)

    def _unique_ref(self,model,field,value):
        key=hashlib.sha256(str(value).strip().lower().encode()).hexdigest()
        return self.root.collection('_unique_'+model.__tablename__+'_'+field).document(key)

    def flush(self):
        # Early uniqueness checks preserve registration's existing 409. Commit
        # repeats the check transactionally, including concurrent registrations.
        for identity in self.new-self.deleted:
            record=self.objects[identity]
            for column in model_inspect(identity[0]).columns:
                value=getattr(record,column.key)
                if column.unique and value is not None:
                    snapshot=self._unique_ref(identity[0],column.key,value).get(timeout=20,retry=None)
                    if snapshot.exists and snapshot.to_dict().get('record_id')!=identity[1]:
                        raise IntegrityError('Unique record already exists',{},None)

    def commit(self):
        from google.cloud import firestore
        from google.api_core.exceptions import ResourceExhausted,ServiceUnavailable,DeadlineExceeded
        from .db import Base
        changes={identity:record_values(record) for identity,record in self.objects.items() if identity not in self.deleted and (identity in self.new or record_values(record)!=self.originals.get(identity))}
        if not changes and not self.deleted:return
        for identity,values in changes.items():
            if identity not in self.new:
                for column in model_inspect(identity[0]).columns:
                    if column.onupdate is not None and values.get(column.key)==self.originals[identity].get(column.key):
                        value=column.onupdate.arg(None);setattr(self.objects[identity],column.key,value);values[column.key]=value
        encoded={identity:encode_record(values) for identity,values in changes.items()}
        total_bytes=sum(len(value.get('_formiqo_payload_zlib',b''))+len(json.dumps({k:v for k,v in value.items() if k!='_formiqo_payload_zlib'},default=json_default,ensure_ascii=False).encode()) for value in encoded.values())
        if total_bytes>MAX_TRANSACTION_BYTES:
            raise HTTPException(413,'This atomic change is too large for Firestore. No partial content was saved.')
        touched=set(changes)|self.deleted
        if len(self.versions)+len(self.new)>MAX_TRANSACTION_RECORDS:
            raise HTTPException(503,'This atomic change exceeds the application batch guard. No partial changes were saved.')
        @firestore.transactional
        def write(transaction):
            models={mapper.local_table.name:mapper.class_ for mapper in Base.registry.mappers}
            references={self.reference(*identity).path:self.reference(*identity) for identity in set(self.versions)|(self.new-self.deleted)}
            for identity,values in changes.items():
                for column in model_inspect(identity[0]).columns:
                    for fk in column.foreign_keys:
                        value=values.get(column.key)
                        parent=(models[fk.column.table.name],value)
                        if value is not None and parent not in self.new:
                            ref=self.reference(*parent);references[ref.path]=ref
            for identity in touched:
                record=self.objects[identity]
                for column in model_inspect(identity[0]).columns:
                    if column.unique:
                        for value in [getattr(record,column.key),self.originals.get(identity,{}).get(column.key)]:
                            if value is not None:
                                ref=self._unique_ref(identity[0],column.key,value);references[ref.path]=ref
            snapshots={s.reference.path:s for s in self.client.get_all(list(references.values()),transaction=transaction,timeout=25,retry=None)}
            # All reads precede writes. Validate every loaded record so authorizing
            # parents cannot be deleted/reassigned while a child is being saved.
            for identity,expected in self.versions.items():
                snapshot=snapshots[self.reference(*identity).path]
                if not snapshot.exists or snapshot.update_time!=expected:
                    raise HTTPException(409,'The saved data changed in another request. Reload before retrying; nothing was overwritten.')
            for identity in self.new-self.deleted:
                snapshot=snapshots[self.reference(*identity).path]
                if snapshot.exists:raise IntegrityError('Record already exists',{},None)
            # Preserve foreign-key existence for all staged child writes. A new
            # parent in this same transaction is valid; a deleted parent is not.
            for identity,values in changes.items():
                for column in model_inspect(identity[0]).columns:
                    for foreign_key in column.foreign_keys:
                        value=values.get(column.key)
                        if value is None:continue
                        parent=(models[foreign_key.column.table.name],value)
                        if parent in self.deleted:raise IntegrityError('Parent record is deleted',{},None)
                        if parent not in self.new:
                            snapshot=snapshots[self.reference(*parent).path]
                            if not snapshot.exists:raise IntegrityError('Parent record does not exist',{},None)
            unique_writes=[]
            for identity in touched:
                record=self.objects[identity]
                for column in model_inspect(identity[0]).columns:
                    if not column.unique:continue
                    old=self.originals.get(identity,{}).get(column.key)
                    value=getattr(record,column.key)
                    candidates=[(value,identity in self.deleted)]
                    if old is not None and old!=value:candidates.append((old,True))
                    for candidate,remove in candidates:
                        if candidate is None:continue
                        ref=self._unique_ref(identity[0],column.key,candidate)
                        snapshot=snapshots[ref.path]
                        if remove:
                            if snapshot.exists and snapshot.to_dict().get('record_id')==identity[1]:unique_writes.append((ref,None))
                        else:
                            if snapshot.exists and snapshot.to_dict().get('record_id')!=identity[1]:
                                raise IntegrityError('Unique record already exists',{},None)
                            unique_writes.append((ref,{'record_id':identity[1]}))
            for identity in self.deleted:
                if identity not in self.new:transaction.delete(self.reference(*identity))
            for identity,values in encoded.items():transaction.set(self.reference(*identity),values)
            for ref,value in unique_writes:
                if value is None:transaction.delete(ref)
                else:transaction.set(ref,value)
        try:
            write(self.client.transaction(max_attempts=3))
        except ResourceExhausted:
            raise HTTPException(503,'The Firestore free quota is exhausted. No SQL fallback was used; retry after the quota resets.') from None
        except (ServiceUnavailable,DeadlineExceeded):
            raise HTTPException(503,'Firestore is temporarily unavailable. Verify the saved revision before retrying.') from None
        # Capture fresh versions after commit. Clear deleted identities before refresh.
        for identity in self.deleted:
            self.objects.pop(identity,None);self.originals.pop(identity,None);self.versions.pop(identity,None)
        self.new.clear();self.deleted.clear()
        refs={self.reference(*identity).path:identity for identity in changes}
        for snapshot in self.client.get_all([self.client.document(path) for path in refs],timeout=25,retry=None):
            identity=refs[snapshot.reference.path]
            if snapshot.exists:
                values=decode_record(snapshot.to_dict());record=self.objects[identity]
                for column in model_inspect(identity[0]).columns:setattr(record,column.key,deepcopy(values.get(column.key)))
                self.originals[identity]=record_values(record);self.versions[identity]=snapshot.update_time

    def rollback(self):
        for identity,values in self.originals.items():
            record=self.objects.get(identity)
            if record:
                for key,value in values.items():setattr(record,key,deepcopy(value))
        self.objects.clear();self.originals.clear();self.versions.clear();self.new.clear();self.deleted.clear()

    def refresh(self,record):
        model=type(record);key=getattr(record,primary_key(model));identity=(model,key)
        snapshot=self.reference(model,key).get(timeout=20,retry=None)
        if not snapshot.exists:raise HTTPException(409,'This record was deleted in another request.')
        values=decode_record(snapshot.to_dict())
        for column in model_inspect(model).columns:setattr(record,column.key,deepcopy(values.get(column.key)))
        self.objects[identity]=record;self.originals[identity]=record_values(record);self.versions[identity]=snapshot.update_time

    def ping(self):
        self.root.get(timeout=10,retry=None)
