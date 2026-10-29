"""Vercel Hobby ASGI entry point: same-origin API plus persistent Firestore/Blob.

A function invocation completes its bounded work before responding. No forever
worker, local SQLite fallback, or leaked developer credential is used in production.
"""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
os.environ['PYTHONPATH']=str(ROOT/'backend')+os.pathsep+os.environ.get('PYTHONPATH','')

os.environ.setdefault('VERCEL_SERVERLESS','true')
os.environ.setdefault('DATABASE_BACKEND','firestore')
os.environ.setdefault('FIREBASE_PROJECT_ID','nitre-d8cdd')
os.environ.setdefault('FIREBASE_NAMESPACE','v1')
os.environ.setdefault('STORAGE_DIR','/tmp/formiqo-private')
os.environ.setdefault('FILE_STORAGE_BACKEND','vercel_blob')
os.environ.setdefault('MAX_UPLOAD_MB','4')  # multipart + headers stay below Vercel's 4.5 MB limit
os.environ.setdefault('MAX_PAGES','20')
os.environ.setdefault('SECURE_COOKIE','true')
os.environ.setdefault('OFFICE_ENABLED','false')
os.environ.setdefault('OMP_THREAD_LIMIT','1')

production='formiqo-six.vercel.app'
origin=os.environ.get('VERCEL_PROJECT_PRODUCTION_URL',production)
hosts=[production,origin,'localhost','127.0.0.1']
for key in ['VERCEL_URL','VERCEL_BRANCH_URL']:
    if os.environ.get(key):hosts.append(os.environ[key])
os.environ.setdefault('ALLOWED_HOSTS',json.dumps(list(set(hosts))))
os.environ.setdefault('ALLOWED_ORIGIN','https://'+origin)
os.environ.setdefault('PUBLIC_URL','https://'+origin)

from app.main import app as application
from app.storage import initialize_storage

# Vercel invokes ASGI HTTP directly; lifespan events are not guaranteed to run.
# Creating this cache is safe at import, while database/OIDC calls are not.
initialize_storage()


class VercelApp:
    async def __call__(self,scope,receive,send):
        # SDK context propagates through anyio's threadpool to Google WIF and Blob.
        if scope['type']=='http':
            from vercel.oidc import set_headers
            headers={k.decode('latin1'):v.decode('latin1') for k,v in scope.get('headers',[])}
            set_headers(headers)
        await application(scope,receive,send)


app=VercelApp()
