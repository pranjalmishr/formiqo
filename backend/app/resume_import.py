"""Conservative layout observations and editable recreation of real source text.

We preserve all extracted text. Font/margin/column observations are estimates;
PDF drawings, images and exact positioned text boxes are not claimed recreated.
"""
import re
from collections import Counter
from html import escape
from statistics import median
from pathlib import Path
import pymupdf
from docx import Document
from .editor_content import DraftContent,Section,DocumentStyle,seed_content
from .scoring import HEADINGS,HEADING_PREFIX,heading_key
from .pdf_layout import analyze_document


def heading(text):
    return heading_key(text)


def clean_title(text):
    """Editable section title: drop numbering/decoration and title-case ALL CAPS.

    The visual uppercase/numbering comes from the template, not the content.
    """
    value=HEADING_PREFIX.sub('',re.sub(r'\s+',' ',text.strip().strip(':')),count=1).strip().strip(':').strip()
    if value.isupper():value=' '.join(word if word in ('UI','UX','IT','AI') else word.capitalize() for word in value.split())
    return value[:100] or text.strip()[:100]


def append_line(sections,text,html):
    if heading(text):sections.append({'id':'section-'+str(len(sections)),'title':clean_title(text),'source_title':text,'parts':[]})
    else:sections[-1]['parts'].append(html)


def join_parts(parts):
    """Concatenate section HTML, merging adjacent single-item lists into one list."""
    return re.sub(r'</ul>\s*<ul>','',''.join(parts))


def profile_source(path:Path,ext:str,text:str,ocr_pages:list[int]):
    sections=[{'id':'contact','title':'Contact information','parts':[]}]
    profile={'format':ext,'columns':1,'font_family':'sans','body_size':10.5,'name_size':27,'accent':'#3448a4','page_size':'A4','margin_mm':15,'page_count':None,'fonts':[],'uncertainties':[],'observations':[]}
    sizes=[];fonts=Counter();colors=Counter();margins=[];page_widths=[];column_pages=[]
    if ext=='pdf' and not ocr_pages:
        with pymupdf.open(path) as pdf:
            profile['page_count']=len(pdf)
            first=pdf[0].rect
            profile['page_size']='LETTER' if abs(first.width-612)<5 and abs(first.height-792)<6 else 'A4'
            # Typography/colour observations come from raw spans; text order comes
            # from the column-aware layout engine so sidebars are not interleaved.
            for page in pdf:
                for block in page.get_text('dict')['blocks']:
                    if block.get('type')!=0:continue
                    for line in block.get('lines',[]):
                        for span in line.get('spans',[]):
                            if not span.get('text','').strip():continue
                            fonts[span.get('font','Unknown')]+=len(span['text']);sizes.extend([span.get('size',10.5)]*min(30,max(1,len(span['text']))))
                            color=span.get('color',0)
                            if color not in (0,16777215) and color>0x101010:colors['#'+format(color,'06x')[-6:]]+=len(span['text'])
            layouts=analyze_document(pdf,lambda value:heading(value) is not None)
            for layout in layouts:
                if layout.paragraphs:margins.append(min(p.x0 for p in layout.paragraphs)*25.4/72)
                for para in layout.paragraphs:
                    html='<ul><li><p>'+para.html+'</p></li></ul>' if para.bullet else '<p>'+para.html+'</p>'
                    append_line(sections,para.text,html)
            removed=[value for layout in layouts for value in layout.removed]
            column_pages=[layout.number for layout in layouts if layout.columns==2]
            if removed:profile['observations'].append(f'{len(removed)} page-number, running-header or decorative line(s) were left out of the editable text: '+', '.join(dict.fromkeys(removed))[:300]+'.')
            if column_pages:
                shares=[layout.left_share for layout in layouts if layout.left_share]
                share=median(shares) if shares else .5
                sidebar=next((layout for layout in layouts if layout.sidebar_fill),None)
                profile['columns']=2;profile['column_ratio']=round(share if share>=.5 else 1-share,2)
                profile['layout']='sidebar-left' if share<.4 else 'sidebar-right' if share>.6 else 'two-column'
                if sidebar:profile['observations'].append(f'A {sidebar.sidebar_side} sidebar background ({sidebar.sidebar_fill}) was detected.')
                profile['observations'].append('Columns were read one at a time (pages '+', '.join(map(str,column_pages))+'), so sidebar and main content are not interleaved.')
                profile['uncertainties'].append('Column layout detected. Verify that each section was assigned to the right heading; exact positions and column widths are approximated by the chosen template.')
            profile['observations'].append('Selectable PDF text, bold/italic runs and list markers were inspected; wrapped lines were rejoined into paragraphs.')
            profile['uncertainties'].append('Original drawings, images, precise alignment, text-box positions and exact line wrapping are not recreated. The retained PDF remains available for comparison.')
    elif ext=='docx':
        doc=Document(path)
        first=doc.sections[0];profile['margin_mm']=round(first.left_margin.mm,1);profile['page_size']='LETTER' if abs(first.page_width.mm-215.9)<2 else 'A4'
        from docx.text.paragraph import Paragraph
        from docx.table import Table
        for child in doc.element.body.iterchildren():
            if child.tag.endswith('}p'):
                para=Paragraph(child,doc);value=para.text.strip()
                if not value:continue
                runs=[]
                for run in para.runs:
                    token=escape(run.text)
                    if run.bold:token='<strong>'+token+'</strong>'
                    if run.italic:token='<em>'+token+'</em>'
                    runs.append(token)
                    if run.font.size:sizes.append(run.font.size.pt)
                    if run.font.name:fonts[run.font.name]+=len(run.text)
                    if run.font.color.rgb:colors['#'+str(run.font.color.rgb).lower()]+=len(run.text)
                html='<p>'+(''.join(runs) if ''.join(r.text for r in para.runs)==para.text else escape(para.text))+'</p>'
                if para._p.xpath('.//w:numPr') or para.style.name.startswith('List'):html='<ul><li>'+html+'</li></ul>'
                append_line(sections,value,html)
            elif child.tag.endswith('}tbl'):
                profile['uncertainties'].append('A Word table was flattened row by row; verify cell reading order and layout.')
                for row in Table(child,doc).rows:
                    value=' | '.join(cell.text for cell in row.cells);append_line(sections,value,'<p>'+escape(value)+'</p>')
        for section in doc.sections:
            cols=section._sectPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cols')
            if cols is not None and int(cols.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num','1'))>1:profile['columns']=2
            for para in list(section.header.paragraphs)+list(section.footer.paragraphs):
                if para.text.strip():append_line(sections,para.text,'<p>'+escape(para.text)+'</p>')
        profile['observations'].append('Word paragraph styles/runs, tables, page settings, header/footer text and column declarations were inspected.')
        profile['uncertainties'].append('Word pagination, text boxes and decorative objects need review. An exact original preview requires Word/LibreOffice; the original DOCX is retained.')
    else:
        sections=[]
        if ocr_pages:profile['uncertainties'].append('OCR text is editable, but original typography and positions cannot be inferred reliably. Verify every recognized word.')
        else:profile['uncertainties'].append('Plain text contains no reliable original font, margin or column information.')
    if fonts:
        profile['fonts']=[{'name':name,'characters':count} for name,count in fonts.most_common(8)]
        dominant=fonts.most_common(1)[0][0].lower();profile['font_family']='mono' if any(v in dominant for v in ('mono','courier','consol')) else 'serif' if any(v in dominant for v in ('times','serif','georgia','cambria','basker')) and 'sans' not in dominant else 'sans'
    if sizes:
        profile['body_size']=round(max(8,min(14,median(sizes))),1);profile['name_size']=round(max(18,min(38,max(sizes))),1)
    if colors:profile['accent']=colors.most_common(1)[0][0]
    if margins:profile['margin_mm']=round(max(8,min(28,median(margins))),1)
    profile['margin_mm']=max(8,min(28,profile['margin_mm']))
    if len(sections)>25:
        profile['uncertainties'].append('Many repeated section headings were detected. The full text was kept in one review stream rather than dropping sections.')
        from .editor_content import text_to_html
        content=DraftContent(sections=[Section(id='full-text',title='Imported resume content',html=text_to_html(text))])
    elif sections:
        content=DraftContent(sections=[Section(id=s['id'],title=s['title'],html=join_parts(s['parts']) or '<p></p>') for s in sections])
        # Any unrepresented extracted tokens remain in an explicit review section.
        source=Counter(re.findall(r'\w+',text.lower()));represented=Counter(re.findall(r'\w+',content.text().lower()))
        # Heading numbering/decoration intentionally removed by clean_title is accounted for.
        for item in sections:
            if item.get('source_title'):represented+=Counter(re.findall(r'\w+',item['source_title'].lower()))-Counter(re.findall(r'\w+',item['title'].lower()))
        missing=source-represented
        if missing:
            profile['uncertainties'].append('Styled extraction may differ from the normalized text. A full extraction reference is preserved; review before recreating.')
            # Use the complete normalized text rather than risk silent content loss.
            content=DraftContent.model_validate(seed_content(text))
    else:content=DraftContent.model_validate(seed_content(text))
    if len(content.sections)==1:profile['uncertainties'].append('No standard section boundaries were recognized. All text remains editable in the contact/unclassified stream; add headings manually.')
    layout_kind=profile.get('layout','two-column')
    if profile['columns']==2:suggested={'sidebar-left':'sidebar-skills','sidebar-right':'experienced'}.get(layout_kind,'two-column')
    else:suggested='classic-ats' if profile['font_family']=='serif' else 'technical' if profile['font_family']=='mono' else 'modern-professional'
    content.template=suggested;content.style=DocumentStyle(page_size=profile['page_size'],font=profile['font_family'],body_size=profile['body_size'],name_size=profile['name_size'],margin_mm=profile['margin_mm'],accent=profile['accent'])
    profile['suggested_template']=suggested
    contact_text=content.sections[0].html
    email=re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)
    profile['detected']={'email':email.group() if email else None,'date_strings':list(dict.fromkeys(re.findall(r'\b(?:19|20)\d{2}(?:[-/]\d{1,2})?\b',text)))[:40],'sections':[s.title for s in content.sections]}
    profile['uncertainties']=list(dict.fromkeys(profile['uncertainties']))
    return {'profile':profile,'content':content.model_dump()}
