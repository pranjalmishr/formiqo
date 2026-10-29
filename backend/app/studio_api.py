"""Visual resume studio APIs over the existing owned EditorDraft model."""
import asyncio
import secrets
import re
from collections import Counter
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session as DBSession
from .db import get_db,Resume,ResumeVersion,EditorDraft,EditorVersion,uid
from .storage import owner,rate_limit
from .auth import retention_expiry
from .editor_api import require,fingerprint,get_editor,commit_draft
from .editor_content import DraftContent,DraftSave,Section,plain_text
from .templates import TEMPLATES,TemplateKey,LEVELS,PROFESSIONS
from .document_renderer import render_document,render_pdf,FONT_FILES,ASSETS,missing_text_tokens
from .studio_docx import studio_docx_bytes,measured_docx_bytes

router=APIRouter(prefix='/api/studio',tags=['Visual document studio'])


def sample_content():
    # Fictional sample is used by gallery routes only, never copied into a user's draft.
    return DraftContent(sections=[
      Section(id='contact',title='Contact information',html='<p><strong>Alex Morgan</strong></p><p>Senior Product Engineer</p><p><a href="mailto:alex@example.com">alex@example.com</a> · Portland, OR · +1 555 010 1020</p><p><a href="https://example.com">example.com/portfolio</a></p>'),
      Section(id='summary',title='Professional Summary',html='<p>Product-minded engineer translating complex requirements into thoughtful, reliable software. Experience across accessible interfaces, data services and collaborative delivery.</p>'),
      Section(id='experience',title='Experience',html='<p><strong>Senior Software Engineer | Northstar Studio</strong></p><p>2021 – Present · Portland, OR</p><ul><li><p>Built accessible planning tools with product and design teams, supporting clear workflows for distributed organizations.</p></li><li><p>Introduced automated integration checks and documented release practices across customer-facing services.</p></li></ul><p><strong>Software Engineer | Fieldwork Labs</strong></p><p>2018 – 2021 · Remote</p><ul><li><p>Developed reporting interfaces and Python services for operational teams.</p></li><li><p>Partnered with researchers to translate customer feedback into practical product improvements.</p></li></ul>'),
      Section(id='skills',title='Technical Skills',html='<p>Python, TypeScript, React, PostgreSQL, Accessibility, API design, Automated testing, Product collaboration</p>'),
      Section(id='education',title='Education',html='<p><strong>B.S. Computer Science | Example University</strong></p><p>2014 – 2018</p><p>Coursework in software systems, data analysis and human-computer interaction.</p>'),
      Section(id='projects',title='Projects',html='<p><strong>Community Data Toolkit</strong></p><p>Python · SQL · React</p><ul><li><p>Created a documented toolkit for exploring public data and sharing readable reports.</p></li></ul>'),
      Section(id='certifications',title='Certifications',html='<p>Accessibility Foundations · Example Learning Institute</p>'),
      Section(id='languages',title='Languages',html='<p>English · Spanish</p>')])


@router.get('/templates')
def templates():
    return {'items':[{'id':key,**value} for key,value in TEMPLATES.items()],'levels':LEVELS,'professions':PROFESSIONS,'sample_notice':'All gallery documents contain fictional sample data, not your resume. Choosing a template starts blank or preserves your existing content.'}


@router.get('/fonts/{filename}')
def font(filename:str):
    path=FONT_FILES.get(filename)
    if not path or not path.is_file():raise HTTPException(404,'Font not found.')
    return FileResponse(path,media_type='font/ttf',headers={'Access-Control-Allow-Origin':'*','Cache-Control':'public, max-age=86400','Cross-Origin-Resource-Policy':'cross-origin'})


@router.get('/runtime.js')
def runtime():
    return FileResponse(ASSETS/'pagination.js',media_type='application/javascript',headers={'Access-Control-Allow-Origin':'*','Cache-Control':'public, max-age=3600','Cross-Origin-Resource-Policy':'cross-origin'})


@router.get('/gallery/{template_id}')
def gallery(template_id:TemplateKey,request:Request):
    content=sample_content();content.template=template_id
    return render_document(content,base_url=str(request.base_url))


class Preview(BaseModel):
    content:DraftContent
    interactive:bool=False


@router.post('/preview')
def preview(data:Preview,request:Request,owner_id=Depends(owner)):
    rate_limit(request,'studio-preview',limit=1200)
    return render_document(data.content,interactive=data.interactive,base_url=str(request.base_url))


class Create(BaseModel):
    template:TemplateKey='classic-ats'
    filename:str=Field(default='Untitled resume',min_length=1,max_length=140)


@router.post('/create',status_code=201)
def create(data:Create,request:Request,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    rate_limit(request,'builder-create')
    identifier=uid();content=DraftContent(template=data.template,sections=[Section(id='contact',title='Contact information',html='<p></p>'),Section(id='summary',title='Professional Summary',html='<p></p>'),Section(id='experience',title='Experience',html='<p></p>'),Section(id='education',title='Education',html='<p></p>'),Section(id='skills',title='Technical Skills',html='<p></p>')])
    text=content.text()
    resume=Resume(id=identifier,owner=owner_id,filename=data.filename,original_format='studio',text=text,original_text='',extraction={'format':'studio','page_count':None,'ocr_pages':[],'warnings':[],'checks':['Structured studio content; verify the selected template reading order']},status='ready',expires_at=retention_expiry(owner_id))
    db.add(resume);db.flush()
    db.add_all([EditorDraft(resume_id=identifier,content=content.model_dump(),revision=1,source_hash=fingerprint(text),applied=[],rejected=[]),EditorVersion(resume_id=identifier,revision=1,content=content.model_dump(),change_summary='Created blank visual studio draft'),ResumeVersion(resume_id=identifier,text=text)])
    db.commit();return get_editor(identifier,owner_id,db)


@router.patch('/{identifier}')
def save(identifier:str,data:DraftSave,request:Request,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    rate_limit(request,'editor-saves',limit=600)
    resume=require(db,identifier,owner_id);draft=db.get(EditorDraft,identifier)
    if not draft:raise HTTPException(409,'Open this resume in the editor before saving.')
    result=commit_draft(db,draft,resume,data)
    metadata={**resume.extraction};warnings=[w for w in metadata.get('warnings',[]) if w.get('code')!='template_columns']
    definition=TEMPLATES[data.content.template]
    columns=data.content.style.columns or definition['columns']
    if columns>1:warnings.append({'code':'template_columns','message':f'The selected {definition["name"]} layout has {columns} columns. Review actual exported text order; compatibility varies by parser.'})
    metadata['warnings']=warnings;metadata['selected_template']=data.content.template;resume.extraction=metadata;db.commit()
    return result


async def owned_content(db,identifier,owner_id):
    resume=require(db,identifier,owner_id);draft=db.get(EditorDraft,identifier)
    if not draft or draft.source_hash!=fingerprint(resume.text):raise HTTPException(409,'Save and synchronize the visual draft before exporting.')
    content=DraftContent.model_validate(draft.content)
    if not any(re.search(r'\w',plain_text(s.html)) for s in content.sections):raise HTTPException(422,'Add real resume content before exporting; blank template labels are not a resume.')
    return resume,content


@router.get('/{identifier}/export')
async def export(identifier:str,request:Request,format:Literal['pdf','docx'],owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    rate_limit(request,'exports')
    _,content=await owned_content(db,identifier,owner_id)
    try:
        if format=='pdf':data,info=await asyncio.wait_for(render_pdf(content),timeout=65)
        else:data=await measured_docx_bytes(content)
    except Exception as exc:
        import logging,traceback
        frames=[(frame.name,frame.lineno) for frame in traceback.extract_tb(exc.__traceback__)[-5:]]
        reason=str(exc)[-2500:] if isinstance(exc,ValueError) or type(exc).__name__=='TargetClosedError' else 'See exception class and frame locations'
        logging.getLogger('formiqo').error('studio_export_failed format=%s class=%s frames=%s reason=%s',format,type(exc).__name__,frames,reason)
        raise HTTPException(503 if format=='pdf' else 422,'Document export could not be validated. PDF rendering requires Chromium (python -m playwright install chromium, or FORMIQO_CHROMIUM). Check the canvas for layout errors before retrying.') from None
    return Response(data,media_type='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':f'attachment; filename="formiqo-resume.{format}"'})


@router.get('/{identifier}/extraction-check')
async def extraction_check(identifier:str,request:Request,owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    rate_limit(request,'exports');_,content=await owned_content(db,identifier,owner_id)
    try:data,info=await asyncio.wait_for(render_pdf(content),timeout=65)
    except Exception:raise HTTPException(503,'Actual export text inspection requires working Chromium rendering.')
    import pymupdf
    with pymupdf.open(stream=data,filetype='pdf') as pdf:
        text='\n\n'.join(p.get_text('text',sort=False) for p in pdf)
        spatial='\n\n'.join(p.get_text('text',sort=True) for p in pdf)
    source=Counter(re.findall(r'\w+',content.text().lower()));result=Counter(re.findall(r'\w+',text.lower()))
    total=sum(source.values());covered=total-sum(missing_text_tokens(content.text(),text).values())
    spatial_tokens=Counter(re.findall(r'\w+',spatial.lower()));spatial_covered=total-sum(missing_text_tokens(content.text(),spatial).values())
    return {'text':text,'spatial_text':spatial,'pages':info['pages'],'source_word_tokens':total,'covered_word_tokens':covered,'coverage':round(100*covered/max(total,1),1),'spatial_coverage':round(100*spatial_covered/max(total,1),1),'warnings':info['warnings'],'notice':'Actual generated PDF: text-stream order is shown, with a spatially sorted alternative for comparison. Sorting across columns can merge or interleave text. Token coverage does not prove correct reading order or universal ATS acceptance.'}
