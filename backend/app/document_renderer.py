"""One HTML/DOM layout engine for gallery, live canvas and Chromium PDF export.

The browser measures and paginates actual blocks; it never shrinks or drops text
just to meet a page preference. Network access is blocked during PDF rendering.
"""
import asyncio
import base64
import json
import os
import secrets
import hashlib
import re
from collections import Counter
from pathlib import Path
from functools import lru_cache
import pymupdf
from .editor_content import DraftContent
from .templates import TEMPLATES
from .processing import native_slots

ASSETS=Path(__file__).parent/'document_assets'
FONT_FILES={'sans.ttf':ASSETS/'fonts'/'sans.ttf','serif.ttf':ASSETS/'fonts'/'serif.ttf','mono.ttf':ASSETS/'fonts'/'mono.ttf'}


def missing_text_tokens(source_text,extracted):
    source=Counter(re.findall(r'\w+',source_text.lower()));output=Counter(re.findall(r'\w+',extracted.lower()));missing=source-output
    # PDF text streams may split a visually wrapped word/URL over line breaks.
    # Count it only when every character remains in sequence with whitespace
    # between; this never treats arbitrary missing characters as present.
    for word in list(missing):
        pattern=r'\b'+r'\s*'.join(re.escape(char) for char in word)+r'\b'
        present=len(re.findall(pattern,extracted.lower()))
        missing[word]=max(0,source[word]-present)
        if not missing[word]:del missing[word]
    return missing


def effective_definition(content:DraftContent):
    value={**TEMPLATES[content.template]}
    style=content.style
    for key in ['font','body_size','heading_size','name_size','leading','spacing','accent','columns','dividers','skills','header','bullet']:
        override=getattr(style,key)
        if override is not None:value[key]=override
    if style.margin_mm is not None:value['margin']=style.margin_mm*72/25.4
    if value['columns']==1 and value['header']=='rail':value['header']='left'
    return value


@lru_cache(maxsize=3)
def font_data(family):
    return base64.b64encode(FONT_FILES[family+'.ttf'].read_bytes()).decode()


def render_document(content:DraftContent,interactive=False,base_url='',embed_fonts=False,token=None):
    definition=effective_definition(content);style=content.style.model_dump();token=token or secrets.token_hex(16)
    fonts=[]
    for family,name in [('sans','StudioSans'),('serif','StudioSerif'),('mono','StudioMono')]:
        source='data:font/ttf;base64,'+font_data(family) if embed_fonts else base_url.rstrip('/')+'/api/studio/fonts/'+family+'.ttf'
        fonts.append(f'@font-face{{font-family:{name};src:url("{source}") format("truetype");font-style:normal;font-weight:100 900;font-display:block}}')
    width,height=(210,297) if style['page_size']=='A4' else (215.9,279.4)
    family={'sans':'StudioSans','serif':'StudioSerif','mono':'StudioMono'}[definition['font']]
    variables=f':root{{--page-w:{width}mm;--page-h:{height}mm;--body:{definition["body_size"]}pt;--heading:{definition["heading_size"]}pt;--name:{definition["name_size"]}pt;--leading:{max(definition["leading"],definition["body_size"]*1.1)}pt;--space:{definition["spacing"]}pt;--margin:{definition["margin"]}pt;--accent:{definition["accent"]}}}body{{font-family:{family},sans-serif}}@page{{size:{width}mm {height}mm;margin:0}}'
    classes=' '.join(['layout-'+definition['layout'],'header-'+definition['header'],'heading-'+definition['heading'],'entries-'+definition['entries'],'skills-'+definition['skills'],'bullet-'+definition['bullet'],'body-'+style['alignment'],'no-dividers' if not definition['dividers'] else ''])
    payload={'content':content.model_dump(),'definition':definition,'style':style,'token':token,'interactive':interactive}
    data=json.dumps(payload,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    nonce=secrets.token_hex(16)
    policy=f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; font-src data: http: https:; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    version=hashlib.sha256((ASSETS/'pagination.js').read_bytes()).hexdigest()[:12]
    runtime='<script nonce="'+nonce+'">'+(ASSETS/'pagination.js').read_text()+'</script>' if embed_fonts else '<script nonce="'+nonce+'" src="'+base_url.rstrip('/')+'/api/studio/runtime.js?v='+version+'"></script>'
    html='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="'+policy+'"><title>Formiqo resume document</title><style>'+''.join(fonts)+variables+(ASSETS/'studio.css').read_text()+'</style></head><body class="'+classes+'"><main class="document-pages" aria-label="Resume document"></main><script type="application/json" id="document-data" nonce="'+nonce+'">'+data+'</script>'+runtime+'</body></html>'
    return {'html':html,'token':token,'width_mm':width,'height_mm':height,'definition':definition}


def browser_path():
    configured=os.environ.get('FORMIQO_CHROMIUM','')
    if configured:return configured
    for candidate in ['/usr/bin/chromium','/usr/bin/chromium-browser','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']:
        if Path(candidate).is_file():return candidate
    from .config import settings
    if settings.vercel_serverless:
        from .lambda_chromium import prepare
        return prepare()
    return None


async def render_pdf(content:DraftContent):
    from .config import settings
    if settings.vercel_serverless:
        from .cdp_pdf import render
        async with native_slots:
            return await asyncio.to_thread(render,content)
    from playwright.async_api import async_playwright
    async with native_slots:
        async with async_playwright() as driver:
            options={'headless':True,'args':['--disable-dev-shm-usage','--disable-background-networking']}
            try:executable=browser_path()
            except Exception as exc:
                import logging
                logging.getLogger('formiqo').error('chromium_prepare_failed class=%s reason=%s',type(exc).__name__,str(exc)[:500])
                raise
            if executable:options['executable_path']=executable
            try:browser=await driver.chromium.launch(**options)
            except Exception as exc:
                import logging
                logging.getLogger('formiqo').error('chromium_launch_failed class=%s reason=%s',type(exc).__name__,str(exc)[-2200:])
                raise
            try:
                page=await browser.new_page(viewport={'width':850,'height':1200},device_scale_factor=1)
                await page.route('**/*',lambda route:route.abort())
                document=render_document(content,embed_fonts=True)
                await page.set_content(document['html'],wait_until='load',timeout=30000)
                await page.wait_for_function('window.__FORMIQO_READY__ || window.__FORMIQO_ERROR__',timeout=30000)
                failure=await page.evaluate('window.__FORMIQO_ERROR__')
                if failure:raise ValueError(failure)
                info=await page.evaluate('window.__FORMIQO_RESULT__')
                info['fit']=await page.evaluate('window.__FORMIQO_FIT__ || null')
                data=await page.pdf(print_background=True,prefer_css_page_size=True,tagged=True)
                with pymupdf.open(stream=data,filetype='pdf') as pdf:
                    if len(pdf)!=info['pages']:raise ValueError('Rendered page count does not match the canvas')
                    if not any(p.get_text().strip() for p in pdf):raise ValueError('Generated PDF contains no selectable text')
                    extracted=' '.join(p.get_text() for p in pdf)
                    missing=missing_text_tokens(content.text(),extracted)
                    if missing:raise ValueError('The PDF text coverage check could not verify every source token. Review long wrapped terms and layout before exporting.')
                    info['text_coverage']=100
                return data,info
            finally:await browser.close()
