import copy
import io
import re
from datetime import timedelta
import pytest
import pymupdf
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app, expire_records
from app.db import Session, Resume, BuilderDraft, EditorDraft, EditorVersion, now
from app.builder_content import BuilderData, to_content
from app.templates import TEMPLATES


def facts():
    return {
        'contact': {'name': 'Avery Morgan', 'email': 'avery@example.com', 'phone': '', 'location': 'Remote', 'website': 'https://example.com/portfolio', 'linkedin': ''},
        'target_role': 'Software Engineer',
        'summary': 'Developed accessible reporting tools and reliable services using verified engineering experience.',
        'experience': [{'title': 'Engineer', 'employer': 'Verified Systems', 'location': 'Remote', 'start': '2021-01', 'end': '', 'current': True, 'highlights': 'Built Python services for actual customer workflows.\nTested deployment checks for internal tools.'}],
        'education': [{'institution': 'Actual College', 'qualification': 'Computer Science coursework', 'start': '2019', 'end': '2021', 'current': False, 'details': 'Relevant software coursework.'}],
        'skills': 'Python, React, SQL',
        'projects': [{'name': 'Reporting Toolkit', 'url': 'https://example.com/project', 'technologies': 'Python, SQL', 'highlights': 'Built a reporting tool for internal teams.'}],
        'certifications': [{'name': 'Verified Training', 'issuer': 'Actual Provider', 'date': '2022', 'url': 'https://example.com/credential'}],
        'achievements': 'Delivered a verified internal workshop.',
        'additional': [{'title': 'Volunteer Experience', 'content': 'Organized a local community workshop.'}],
        'template': 'classic-ats', 'step': 10,
    }


def create(client, data=None):
    result = client.post('/api/builder/create', json=facts() if data is None else data)
    assert result.status_code == 201, result.text
    return result.json()


def test_create_save_resume_and_editor_sync(client):
    d = create(client)
    rid = d['resume_id']
    assert d['revision'] == 1 and not d['out_of_sync'] and not d['export_issues']
    assert len(client.get('/api/builder').json()['items']) == 1
    listed = client.get('/api/resumes').json()['items'][0]
    assert listed['has_builder'] and listed['original_format'] == 'builder'
    assert client.get('/api/editor/'+rid).json()['content'] == d['content']
    d['data']['summary'] = 'Built verified tools to help actual internal teams.'
    d['data']['template'] = 'technical'
    d['data']['step'] = 8
    result = client.patch('/api/builder/'+rid, json={'revision': d['revision'], 'data': d['data']})
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved['revision'] == 2 and saved['data']['step'] == 8
    assert saved['content']['template'] == 'technical'
    assert 'Built verified tools' in client.get('/api/resumes/'+rid).json()['text']
    assert client.get('/api/editor/'+rid).json()['revision'] == 2
    assert len(client.get('/api/editor/'+rid+'/versions').json()['items']) == 2
    result = client.patch('/api/builder/'+rid, json={'revision': saved['revision'], 'data': saved['data']})
    assert result.json()['revision'] == 2  # Unchanged saves do not fabricate versions.


def test_incomplete_drafts_allowed_but_exports_blocked(client):
    d = create(client, {})
    assert d['export_issues']
    result = client.post('/api/builder/'+d['resume_id']+'/export?format=pdf')
    assert result.status_code == 422 and 'name' in result.json()['detail']
    student = create(client, {'contact': {'name': 'Alex Student', 'phone': '+1 555 010 1234'}, 'education': [{'institution': 'Actual School', 'qualification': 'Current coursework', 'current': True}]})
    assert not student['export_issues']
    assert [s['title'] for s in student['content']['sections']] == ['Contact information', 'Education']
    assert client.post('/api/builder/'+student['resume_id']+'/export?format=pdf').status_code == 200


@pytest.mark.parametrize('template', list(TEMPLATES))
def test_each_template_has_actual_readable_pdf_and_docx(client, template):
    data = facts()
    data['template'] = template
    data['section_order'] = ['summary', 'skills', 'experience', 'education', 'projects', 'certifications', 'achievements', 'additional']
    d = create(client, data)
    rid = d['resume_id']
    result = client.post('/api/builder/'+rid+'/export?format=pdf')
    assert result.status_code == 200, result.text[:100]
    assert result.content.startswith(b'%PDF-')
    with pymupdf.open(stream=result.content, filetype='pdf') as pdf:
        text = '\n'.join(page.get_text() for page in pdf)
        assert 'Avery Morgan' in ' '.join(text.split()) and 'Verified Systems' in ' '.join(text.split()) and 'Present' in text
        normalized=' '.join(text.casefold().split())
        assert 'technical skills' in normalized and 'experience' in normalized
        # Single streams preserve the requested order. Column templates place
        # skills in their declared rail, so reading order is explicitly reviewed.
        if TEMPLATES[template]['columns']==1:
            skill_heading=re.search(r'^\s*(?:\d+\s+)?technical\s+skills\s*$',text,re.I|re.M)
            experience_heading=re.search(r'^\s*(?:\d+\s+)?experience\s*$',text,re.I|re.M)
            assert skill_heading and experience_heading and skill_heading.start()<experience_heading.start()
        assert any(page.get_links() for page in pdf)
        assert abs(pdf[0].rect.width - 595.28) < 1
    result = client.post('/api/builder/'+rid+'/export?format=docx')
    assert result.status_code == 200
    doc = Document(io.BytesIO(result.content))
    from docx.oxml.ns import qn
    text=' '.join(node.text or '' for node in doc.element.body.iter(qn('w:t'))).casefold()
    assert 'technical skills' in text and 'experience' in text and 'verified systems' in text
    if TEMPLATES[template]['columns']==1:
        headings=[]
        for paragraph in doc.element.body.iter(qn('w:p')):
            style=paragraph.find('./'+qn('w:pPr')+'/'+qn('w:pStyle'))
            if style is not None and style.get(qn('w:val'))=='Heading1':
                value=''.join(node.text or '' for node in paragraph.iter(qn('w:t'))).casefold().strip()
                headings.append(re.sub(r'^\d+\s+','',value))
        assert headings.index('technical skills')<headings.index('experience')
    assert any(node.get(qn('w:val'))=='ListBullet' for node in doc.element.body.iter(qn('w:pStyle')))
    if TEMPLATES[template]['columns']>1 or TEMPLATES[template]['layout']=='labelled':assert doc.tables
    assert any(rel.is_external and 'https://example.com' in rel.target_ref for rel in doc.part.rels.values())
    assert doc.styles['Normal'].font.size.pt == TEMPLATES[template]['body_size']


def test_multipage_output_retains_last_entry(client):
    data = facts()
    data['experience'][0]['highlights'] = '\n'.join('Built verified tool '+str(i)+' for internal reporting and actual customer workflows.' for i in range(100))
    d = create(client, data)
    result = client.post('/api/builder/'+d['resume_id']+'/export?format=pdf')
    assert result.status_code == 200
    with pymupdf.open(stream=result.content, filetype='pdf') as pdf:
        assert len(pdf) > 1
        assert 'Verified Training' in '\n'.join(page.get_text() for page in pdf)


def test_revision_and_external_changes_do_not_get_overwritten(client):
    d = create(client)
    rid = d['resume_id']
    data = copy.deepcopy(d['data'])
    data['summary'] = 'Built verified newer resume content.'
    saved = client.patch('/api/builder/'+rid, json={'revision': 1, 'data': data})
    assert saved.status_code == 200
    assert client.patch('/api/builder/'+rid, json={'revision': 1, 'data': d['data']}).status_code == 409
    editor = client.get('/api/editor/'+rid).json()
    editor['content']['sections'][1]['html'] = '<p>Newer editor text must not be overwritten.</p>'
    result = client.patch('/api/editor/'+rid, json={'revision': editor['revision'], 'content': editor['content']})
    assert result.status_code == 200
    assert client.get('/api/builder/'+rid).json()['out_of_sync']
    assert client.patch('/api/builder/'+rid, json={'revision': 2, 'data': data}).status_code == 409
    assert client.post('/api/builder/'+rid+'/export?format=pdf').status_code == 409
    copy_draft = create(client, data)
    assert copy_draft['resume_id'] != rid
    assert 'Newer editor text' in client.get('/api/resumes/'+rid).json()['text']


def test_editor_keeps_builder_template(client):
    data = facts()
    data['template'] = 'minimalist'
    d = create(client, data)
    editor = client.get('/api/editor/'+d['resume_id']).json()
    editor['content']['sections'][1]['html'] += '<p>Actual additional detail.</p>'
    response = client.patch('/api/editor/'+d['resume_id'], json={'revision':editor['revision'], 'content':editor['content']})
    assert response.status_code == 200 and response.json()['content']['template'] == 'minimalist'
    assert client.get('/api/editor/'+d['resume_id']+'/export?format=docx').status_code == 200


@pytest.mark.parametrize('patch', [
    {'contact': {'email': 'invalid'}},
    {'contact': {'website': 'javascript:alert(1)'}},
    {'contact': {'website': 'https://user:pass@example.com'}},
    {'template': 'imaginary'},
    {'step': 11},
    {'section_order': ['skills'] * 8},
    {'experience': [{'start': '2025-12', 'end': '2024-01'}]},
    {'education': [{'start': '2025-12', 'end': '2025-01'}]},
    {'education': [{'current': True, 'end': '2024'}]},
    {'certifications': [{'date': '2024-15'}]},
    {'projects': [{'url': 'file:///etc/passwd'}]},
    {'unexpected': 'field'},
])
def test_invalid_input_rejected(client, patch):
    response = client.post('/api/builder/create', json=patch)
    assert response.status_code == 422


def test_preview_escapes_untrusted_content(client):
    data = facts()
    data['summary'] = '<script>bad()</script><img src=x onerror=bad()>Actual text'
    response = client.post('/api/builder/preview', json=data)
    assert response.status_code == 200
    section = next(s for s in response.json()['content']['sections'] if s['id'] == 'summary')
    assert '<script>' not in section['html'] and '<img' not in section['html']
    assert '&lt;script&gt;' in section['html']
    assert client.get('/api/builder').json()['items'] == []  # Preview never stores a draft.


def test_ownership_deletion_and_expiry(client):
    d = create(client)
    rid = d['resume_id']
    with TestClient(app) as other:
        other.get('/api/config')
        assert other.get('/api/builder/'+rid).status_code == 404
        assert other.patch('/api/builder/'+rid,json={'revision':1,'data':d['data']}).status_code == 404
        assert other.post('/api/builder/'+rid+'/export?format=pdf').status_code == 404
        assert other.get('/api/builder').json()['items'] == []
    assert client.delete('/api/resumes/'+rid).status_code == 204
    with Session() as db:
        assert db.get(BuilderDraft,rid) is None
        assert db.get(EditorDraft,rid) is None
    d = create(client)
    with Session() as db:
        resume = db.get(Resume,d['resume_id'])
        resume.expires_at = now() - timedelta(minutes=1)
        db.commit()
    assert client.get('/api/builder/'+d['resume_id']).status_code == 404
    expire_records()
    with Session() as db:
        assert db.get(BuilderDraft,d['resume_id']) is None


def test_no_ai_or_fake_content_added(client):
    data = {'contact': {'name': 'Alex', 'email': 'alex@example.com'}, 'skills': 'Writing, research'}
    d = create(client,data)
    text = client.get('/api/resumes/'+d['resume_id']).json()['text']
    assert 'Experience' not in text and 'Education' not in text and 'Certifications' not in text
    assert 'Writing, research' in text
    assert client.post('/api/builder/'+d['resume_id']+'/export?format=png').status_code == 422


def test_multiline_titles_and_expanded_html_limits_return_validation_errors(client):
    assert client.post('/api/builder/create', json={'additional': [{'title': 'Languages\nInvalid title', 'content': 'Actual language'}]}).status_code == 422
    large = {'summary': '<' * 12000, 'skills': '<' * 6000, 'achievements': '<' * 12000,
             'additional': [{'title': 'Section '+str(i), 'content': '<' * 12000} for i in range(5)]}
    assert client.post('/api/builder/preview', json=large).status_code == 422


def test_date_only_unfinished_entries_block_export(client):
    d = create(client, {'contact': {'name': 'Alex', 'email': 'alex@example.com'}, 'experience': [{'current': True}], 'education': [{'start': '2023'}]})
    assert any('role and employer' in issue for issue in d['export_issues'])
    assert any('institution' in issue for issue in d['export_issues'])
    assert client.post('/api/builder/'+d['resume_id']+'/export?format=pdf').status_code == 422


def test_serif_export_keeps_accented_names(client):
    data = facts()
    data['contact']['name'] = 'Zoë García'
    d = create(client, data)
    result = client.post('/api/builder/'+d['resume_id']+'/export?format=pdf')
    assert result.status_code == 200
    with pymupdf.open(stream=result.content, filetype='pdf') as pdf:
        assert 'Zoë García' in '\n'.join(page.get_text() for page in pdf)
