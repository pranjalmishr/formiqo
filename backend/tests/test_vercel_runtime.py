"""Regression coverage for the real failures found on Vercel Hobby.

Private Blob is mocked here; live production browser tests verify the actual store.
Cold-start tests delete the entire local job cache between HTTP requests.
"""
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from contextlib import contextmanager

import pymupdf
import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app import durable_files
from app.main import app


@pytest.fixture
def private_blob(monkeypatch):
    from vercel.blob import sync,BlobNotFoundError
    objects={}
    def put(key,body,**options):
        assert options['access']=='private' and options['add_random_suffix'] is False
        objects[key]=body.read() if hasattr(body,'read') else bytes(body)
        return SimpleNamespace(url='https://private.example/'+key)
    @contextmanager
    def stream(key,**options):
        assert options['access']=='private'
        if key not in objects:raise BlobNotFoundError('Not found')
        yield iter([objects[key]])
    def delete(keys,**options):
        for key in keys if isinstance(keys,list) else [keys]:objects.pop(key.removeprefix('https://private.example/'),None)
    def listing(prefix=None,**options):
        return [SimpleNamespace(url=key) for key in objects if key.startswith(prefix)]
    def head(key):
        if key not in objects:raise BlobNotFoundError('Not found')
        return SimpleNamespace(size=len(objects[key]))
    monkeypatch.setattr(sync,'put_blob',put);monkeypatch.setattr(sync,'stream_blob',stream)
    monkeypatch.setattr(sync,'delete_blob',delete);monkeypatch.setattr(sync,'query_blobs',listing)
    monkeypatch.setattr(sync,'head_blob',head)
    monkeypatch.setattr(settings,'file_storage_backend','vercel_blob')
    return objects


def test_blob_paths_cannot_escape_private_storage(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'storage_dir',tmp_path/'private')
    with pytest.raises(ValueError):durable_files.object_key(tmp_path/'not-private.txt')
    with pytest.raises(ValueError):durable_files.object_key(tmp_path/'private')


def test_native_workers_inherit_imports_but_not_server_secrets(monkeypatch,tmp_path):
    from app.native_env import worker_env
    import sys
    for name in ['BLOB_READ_WRITE_TOKEN','LLM_API_KEY','SMTP_PASSWORD','GOOGLE_APPLICATION_CREDENTIALS','DATABASE_URL']:
        monkeypatch.setenv(name,'synthetic-secret')
    env=worker_env(tmp_path)
    assert all(name not in env for name in ['BLOB_READ_WRITE_TOKEN','LLM_API_KEY','SMTP_PASSWORD','GOOGLE_APPLICATION_CREDENTIALS','DATABASE_URL'])
    assert 'PYTHONPATH' in env and env['TMPDIR']==str(tmp_path)
    assert any(path in env['PYTHONPATH'] for path in sys.path if path)


def test_blob_cache_is_disposable(private_blob):
    path=settings.storage_dir/'originals'/'synthetic.txt';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'Actual private data')
    durable_files.persist(path);path.unlink()
    assert durable_files.hydrate(path) and path.read_bytes()==b'Actual private data'
    durable_files.remove(path)
    assert not durable_files.hydrate(path) and private_blob=={}


def test_serverless_upload_finishes_before_response_and_retains_original(client,private_blob,monkeypatch):
    monkeypatch.setattr(settings,'vercel_serverless',True)
    text=b'Alex Example\nalex@example.com\nExperience\nBuilt actual services for 12 teams.\nSkills\nPython, SQL'
    response=client.post('/api/resumes/upload',files={'file':('synthetic.txt',text,'text/plain')})
    assert response.status_code==202,response.text
    row=response.json();assert row['status']=='ready' and row['text']
    assert client.get('/api/imports/'+row['id']).json()['original_available'] is True
    shutil.rmtree(settings.storage_dir/'originals')  # cold start of a different instance
    original=client.get('/api/imports/'+row['id']+'/original')
    assert original.status_code==200 and original.content==text
    with TestClient(app) as other:
        other.get('/api/config')
        assert other.get('/api/imports/'+row['id']+'/original').status_code==404
    assert client.delete('/api/resumes/'+row['id']).status_code==204
    assert private_blob=={}


def test_prepared_job_and_download_survive_cold_starts(client,private_blob,monkeypatch):
    monkeypatch.setattr(settings,'vercel_serverless',True)
    pdf=pymupdf.open();pdf.new_page().insert_text((40,40),'Actual synthetic PDF text.');data=pdf.tobytes()
    response=client.post('/api/tools/prepare',data={'tool':'pdf-merge'},files=[('files',('one.pdf',data,'application/pdf')),('files',('two.pdf',data,'application/pdf'))])
    assert response.status_code==202,response.text
    row=response.json();assert row['status']=='prepared'
    from app.converter_api import job_dir
    shutil.rmtree(job_dir(row['id']),ignore_errors=True)
    # Preview creates parents and hydrates its input on an empty instance cache.
    thumb=client.get('/api/tools/'+row['id']+'/thumbnail')
    assert thumb.status_code==200,thumb.text
    shutil.rmtree(job_dir(row['id']),ignore_errors=True)
    result=client.post('/api/tools/'+row['id']+'/run',json={'settings':{'file_order':[1,0]},'file_order':[1,0]})
    assert result.status_code==202,result.text
    assert result.json()['status']=='completed',result.text
    shutil.rmtree(job_dir(row['id']),ignore_errors=True)
    downloaded=client.get('/api/converter/jobs/'+row['id']+'/download')
    assert downloaded.status_code==200
    with pymupdf.open(stream=downloaded.content,filetype='pdf') as merged:assert len(merged)==2
    shutil.rmtree(job_dir(row['id']),ignore_errors=True)
    assert client.get('/api/tools/'+row['id']+'/output-thumbnail').status_code==200
    assert client.delete('/api/converter/jobs/'+row['id']).status_code==204
    assert private_blob=={}


def test_cron_requires_secret_and_uses_existing_cleanup(client,monkeypatch):
    import app.main as main
    calls=[]
    monkeypatch.setenv('CRON_SECRET','synthetic-cron-secret')
    monkeypatch.setattr(main,'expire_records',lambda:calls.append(True))
    assert client.get('/api/maintenance/cleanup').status_code==403
    assert client.get('/api/maintenance/cleanup',headers={'Authorization':'Bearer wrong'}).status_code==403
    assert client.get('/api/maintenance/cleanup',headers={'Authorization':'Bearer synthetic-cron-secret'}).status_code==200
    assert calls==[True]


def test_deployment_manifests_are_consistent_and_do_not_require_external_api():
    root=Path(__file__).resolve().parents[2]
    pins=lambda p:[line.strip() for line in p.read_text().splitlines() if line.strip() and not line.startswith('#')]
    assert pins(root/'requirements.txt')==pins(root/'backend/requirements-vercel.txt')
    assert not any(line.startswith('playwright') for line in pins(root/'requirements.txt'))
    config=json.loads((root/'vercel.json').read_text())
    assert 'FORMIQO_API_ORIGIN' not in config['buildCommand']
    assert config['functions']['api/index.py']['maxDuration']==300
    assert config['crons']==[{'path':'/api/maintenance/cleanup','schedule':'0 4 * * *'}]


@pytest.mark.parametrize('template',['classic-ats','sidebar-skills','two-column','contemporary-creative'])
def test_lean_cdp_renderer_preserves_real_document_geometry(template):
    from app.document_renderer import browser_path
    from app.studio_api import sample_content
    from app.cdp_pdf import render
    executable=browser_path()
    if not executable:pytest.skip('Chromium is required')
    content=sample_content();content.template=template
    data,info=render(content,executable=executable)
    assert info['pages']==1 and info['text_coverage']==100
    with pymupdf.open(stream=data,filetype='pdf') as document:
        assert len(document)==1 and 'Alex Morgan' in ' '.join(document[0].get_text().split())
