import asyncio
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.config import settings
from app.db import Session,User,AuthSession,Resume,now
from app.auth import hash_password,verify_password,digest
from app.intelligence import AssistantResponse

PASSWORD='a unique test passphrase 2026!'


def signup(client,email='alex@example.com',claim=False):
    result=client.post('/api/auth/register',json={'name':'Alex Example','email':email,'password':PASSWORD,'claim_guest':claim})
    assert result.status_code==201,result.text
    return result.json()


def resume(client):
    result=client.post('/api/builder/create',json={'contact':{'name':'Alex Example','email':'alex@example.com'},'summary':'Developed verified Python services and accessible tools for actual internal workflows.','skills':'Python, React, SQL','experience':[{'title':'Engineer','employer':'Actual Company','highlights':'Built Python tools for actual customer workflows.'}]})
    assert result.status_code==201,result.text
    return result.json()


def test_salted_hashes_and_password_validation():
    a,b=hash_password(PASSWORD),hash_password(PASSWORD)
    assert a!=b and PASSWORD not in a and verify_password(PASSWORD,a) and not verify_password('wrong',a)


def test_account_login_logout_refresh_and_claim(client):
    guest=resume(client);rid=guest['resume_id']
    signed=signup(client,claim=True);assert signed['user']['email']=='alex@example.com'
    assert client.get('/api/auth/me').json()['user']['id']==signed['user']['id']
    old_cookie=client.cookies.get('formiqo_auth');assert old_cookie and len(old_cookie)==64
    assert client.post('/api/auth/refresh').status_code==200
    assert client.cookies.get('formiqo_auth')!=old_cookie
    with Session() as db:
        assert db.get(AuthSession,digest(old_cookie)) is None
        row=db.get(Resume,rid);assert row.owner.startswith('u_') and row.expires_at.replace(tzinfo=now().tzinfo)>now()+timedelta(days=300)
        user=db.scalar(select(User).where(User.email=='alex@example.com'));assert user.password_hash!=PASSWORD
    assert client.post('/api/auth/logout').status_code==204
    assert client.get('/api/resumes/'+rid).status_code==404
    assert client.post('/api/auth/login',json={'email':'alex@example.com','password':'wrong password here'}).status_code==401
    assert client.post('/api/auth/login',json={'email':'alex@example.com','password':PASSWORD}).status_code==200
    assert client.get('/api/resumes/'+rid).status_code==200
    with TestClient(app) as another:
        another.get('/api/config');assert another.get('/api/resumes/'+rid).status_code==404
        assert another.post('/api/auth/login',json={'email':'alex@example.com','password':PASSWORD}).status_code==200
        assert another.get('/api/resumes/'+rid).status_code==200
        assert len(client.get('/api/auth/sessions').json()['items'])==2
        assert client.post('/api/auth/revoke-other-sessions').status_code==204
        assert another.get('/api/auth/me').json()['user'] is None


def test_guest_data_not_claimed_without_consent(client):
    draft=resume(client)
    signup(client,claim=False)
    assert client.get('/api/resumes/'+draft['resume_id']).status_code==404
    assert client.post('/api/auth/logout').status_code==204
    assert client.get('/api/resumes/'+draft['resume_id']).status_code==200


def test_smtp_missing_does_not_claim_email_sent(client,monkeypatch):
    monkeypatch.setattr(settings,'smtp_host','')
    result=client.post('/api/auth/forgot-password',json={'email':'alex@example.com'})
    assert result.status_code==503 and 'no email was sent' in result.json()['detail']
    assert client.post('/api/auth/resend-verification',json={'email':'alex@example.com'}).status_code==503


def test_reset_and_verification_one_time_tokens(client,monkeypatch):
    signup(client)
    messages=[]
    monkeypatch.setattr(settings,'smtp_host','configured.test')
    monkeypatch.setattr('app.auth.send_mail',lambda address,purpose,token:messages.append((address,purpose,token)))
    response=client.post('/api/auth/forgot-password',json={'email':'alex@example.com'})
    assert response.status_code==200 and 'token' not in response.json()
    token=messages[-1][2]
    new='another unique test passphrase!'
    assert client.post('/api/auth/reset-password',json={'token':token,'password':new}).status_code==200
    assert client.get('/api/auth/me').json()['user'] is None
    assert client.post('/api/auth/reset-password',json={'token':token,'password':new}).status_code==400
    assert client.post('/api/auth/login',json={'email':'alex@example.com','password':PASSWORD}).status_code==401
    assert client.post('/api/auth/login',json={'email':'alex@example.com','password':new}).status_code==200
    assert client.post('/api/auth/resend-verification',json={'email':'alex@example.com'}).status_code==200
    token=messages[-1][2]
    assert client.post('/api/auth/verify-email',json={'token':token}).status_code==200
    assert client.get('/api/auth/me').json()['user']['verified']
    assert client.post('/api/auth/verify-email',json={'token':token}).status_code==400


def test_required_verification_and_account_deletion(client,monkeypatch):
    monkeypatch.setattr(settings,'require_email_verification',True);monkeypatch.setattr(settings,'smtp_host','configured.test')
    messages=[];monkeypatch.setattr('app.auth.send_mail',lambda address,purpose,token:messages.append(token))
    created=signup(client);assert created['user'] is None
    assert client.post('/api/auth/login',json={'email':'alex@example.com','password':PASSWORD}).status_code==403
    assert client.post('/api/auth/verify-email',json={'token':messages[-1]}).status_code==200
    assert client.post('/api/auth/login',json={'email':'alex@example.com','password':PASSWORD}).status_code==200
    draft=resume(client)
    assert client.request('DELETE','/api/auth/account',json={'password':'incorrect password'}).status_code==401
    assert client.request('DELETE','/api/auth/account',json={'password':PASSWORD}).status_code==204
    assert client.get('/api/auth/me').json()['user'] is None
    assert client.get('/api/resumes/'+draft['resume_id']).status_code==404
    with Session() as db:assert db.scalar(select(User).where(User.email=='alex@example.com')) is None


def test_optional_guest_disable_and_account_flag(client,monkeypatch):
    monkeypatch.setattr(settings,'guest_allowed',False)
    assert client.get('/api/config').status_code==200
    assert client.get('/api/resumes').status_code==401
    monkeypatch.setattr(settings,'accounts_enabled',False)
    assert client.post('/api/auth/register',json={'name':'Alex','email':'a@example.com','password':PASSWORD}).status_code==503


def test_dedicated_match_and_content_preserving_tailor(client):
    d=resume(client);rid=d['resume_id'];jd='Required: Python and SQL. Preferred: AWS. Responsibilities include Python engineering and SQL reporting.'
    result=client.post('/api/ai/match-job-description',json={'resume_id':rid,'job_description':jd})
    assert result.status_code==201,result.text
    data=result.json();assert 'python' in data['keywords']['found'] and 'aws' in data['keywords']['missing'] and 0<=data['match_score']<=100
    original=client.get('/api/editor/'+rid).json()
    payload={'resume_id':rid,'revision':original['revision'],'job_description':jd}
    preview=client.post('/api/ai/tailor-resume',json=payload)
    assert preview.status_code==200
    proposed=preview.json()['content']['sections']
    assert {s['id']:s['html'] for s in proposed}=={s['id']:s['html'] for s in original['content']['sections']}
    assert client.post('/api/ai/tailor-resume',json={**payload,'create_copy':True}).status_code==422
    created=client.post('/api/ai/tailor-resume',json={**payload,'create_copy':True,'facts_confirmed':True})
    assert created.status_code==200 and created.json()['resume_id']!=rid
    assert client.get('/api/editor/'+rid).json()['content']==original['content']
    assert client.get('/api/editor/'+created.json()['resume_id']+'/export?format=pdf').status_code==200


def test_local_assistant_no_external_calls(client,monkeypatch):
    d=resume(client)
    async def forbidden(*args):raise AssertionError('External AI must not be called without consent')
    monkeypatch.setattr('app.intelligence.llm_assistant',forbidden)
    result=client.post('/api/ai/assistant',json={'resume_id':d['resume_id'],'question':'Which keywords are relevant?','job_description':'Required Python and AWS engineering experience. Preferred SQL skills.'})
    assert result.status_code==200 and result.json()['mode']=='local' and result.json()['proposal'] is None


def test_assistant_grounding_and_explicit_apply(client,monkeypatch):
    d=resume(client);rid=d['resume_id'];editor=client.get('/api/editor/'+rid).json();section=next(s for s in editor['content']['sections'] if s['id']=='summary')
    from app.editor_content import plain_text
    source=plain_text(section['html'])
    monkeypatch.setattr(settings,'llm_api_key','synthetic-test-only')
    async def reply(*args):return AssistantResponse.model_validate({'answer':'Clarify the actual outcome in your summary.','citations':[{'section_id':'summary','quote':source},{'section_id':'summary','quote':'Invented citation'}],'proposal':{'section_id':'summary','original':source,'suggested':'Developed verified Python services for actual internal workflows.','notes':['Verify all facts.']}})
    monkeypatch.setattr('app.intelligence.llm_assistant',reply)
    response=client.post('/api/ai/assistant',json={'resume_id':rid,'question':'Improve my summary','ai_consent':True})
    assert response.status_code==200,response.text
    result=response.json();assert result['mode']=='ai' and len(result['citations'])==1
    assert client.get('/api/editor/'+rid).json()['content']==editor['content']
    payload={'resume_id':rid,'revision':result['revision'],'proposal':result['proposal'],'facts_confirmed':False}
    assert client.post('/api/ai/apply-proposal',json=payload).status_code==422
    payload['facts_confirmed']=True
    assert client.post('/api/ai/apply-proposal',json=payload).status_code==200
    assert client.post('/api/ai/apply-proposal',json=payload).status_code==409
    assert 'actual internal workflows' in client.get('/api/resumes/'+rid).json()['text']


def test_service_secrets_not_embedded_in_public_urls_and_jd_clauses():
    from app.config import Settings
    from app.scoring import keywords
    for url in ['https://user:secret@example.com/v1','https://example.com/v1?api_key=secret']:
        with pytest.raises(ValueError):Settings(llm_base_url=url)
    result=keywords('Required: Python. Preferred: AWS. Responsibilities: build SQL reports.','Python SQL')
    assert result['groups']['required']==['Required: Python.']
    assert result['groups']['preferred']==['Preferred: AWS.']
    assert result['groups']['responsibilities']==['Responsibilities: build SQL reports.']


def test_activity_and_usage_are_actual_owned_records(client):
    assert client.get('/api/activity').json()['items']==[]
    before=client.get('/api/usage').json()['buckets']['analyses']['used']
    d=resume(client)
    assert any(item['label']=='Resume draft saved' for item in client.get('/api/activity').json()['items'])
    result=client.post('/api/ai/match-job-description',json={'resume_id':d['resume_id'],'job_description':'Required Python engineering and SQL skills. Preferred React experience.'})
    assert result.status_code==201
    assert client.get('/api/usage').json()['buckets']['analyses']['used']==before+1
    events=client.get('/api/activity').json()['items']
    assert any(item['label']=='Resume analyzed' and str(result.json()['overall_score']) in item['detail'] for item in events)
    with TestClient(app) as other:
        other.get('/api/config');assert other.get('/api/activity').json()['items']==[]
