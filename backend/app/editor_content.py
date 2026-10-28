"""Sanitized section content shared by editor persistence and exports.

Only a small ATS-readable HTML subset is accepted. No images, arbitrary CSS,
remote resources, scripts or embedded content are rendered or exported.
"""
import re
from html import escape
from html.parser import HTMLParser
from typing import Literal
import bleach
from pydantic import BaseModel, Field, field_validator, model_validator
from .scoring import HEADINGS, heading_key
from .templates import TemplateKey

TAGS = ['p', 'br', 'strong', 'em', 'u', 'ul', 'ol', 'li', 'h2', 'h3', 'a']


def clean_html(value: str):
    value = re.sub(r'<(script|style)[^>]*>.*?</\1\s*>', '', value, flags=re.I | re.S)
    return bleach.clean(value, tags=TAGS, attributes={'a': ['href']}, protocols=['http', 'https', 'mailto'], strip=True, strip_comments=True)


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('p', 'h2', 'h3', 'li'):
            if not (tag == 'p' and self.parts and self.parts[-1] == '• '):
                self.parts.append('\n')
        if tag == 'li':
            self.parts.append('• ')
        if tag == 'br':
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('p', 'h2', 'h3', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value: str):
    parser = TextParser()
    parser.feed(value)
    return re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip()


def text_to_html(value: str):
    return ''.join(f'<p>{escape(line)}</p>' for line in value.splitlines() if line.strip()) or '<p></p>'


class Section(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    title: str = Field(min_length=1, max_length=100)
    html: str = Field(max_length=100000)
    page_break_before: bool = False
    placement: Literal['auto','main','rail'] = 'auto'

    @field_validator('title')
    @classmethod
    def title_text(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError('Section titles must be nonempty single-line text')
        return value.strip()

    @field_validator('html')
    @classmethod
    def safe_content(cls, value):
        return clean_html(value)


class DocumentStyle(BaseModel):
    model_config = {'extra': 'forbid'}
    page_size: Literal['A4','LETTER'] = 'A4'
    font: Literal['sans','serif','mono'] | None = None
    body_size: float | None = Field(default=None, ge=8, le=14)
    heading_size: float | None = Field(default=None, ge=9, le=20)
    name_size: float | None = Field(default=None, ge=18, le=38)
    leading: float | None = Field(default=None, ge=10, le=24)
    spacing: float | None = Field(default=None, ge=2, le=18)
    margin_mm: float | None = Field(default=None, ge=8, le=28)
    accent: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')
    columns: Literal[1,2] | None = None
    header: Literal['left','center','split','band','code','masthead','rail'] | None = None
    bullet: Literal['disc','dash','square'] | None = None
    dividers: bool | None = None
    skills: Literal['text','tags','grid','rules'] | None = None
    alignment: Literal['left','justify'] = 'left'
    date_alignment: Literal['left','right'] = 'left'
    page_limit: int = Field(default=2, ge=1, le=10)
    auto_fit: bool = True  # tighten spacing (bounded) when only a short tail spills onto a new page


class DraftContent(BaseModel):
    sections: list[Section] = Field(min_length=1, max_length=25)
    template: TemplateKey = 'classic-ats'
    style: DocumentStyle = Field(default_factory=DocumentStyle)

    @model_validator(mode='after')
    def bounded(self):
        if len({s.id for s in self.sections}) != len(self.sections):
            raise ValueError('Section IDs must be unique')
        if sum(len(s.html) for s in self.sections) > 200000:
            raise ValueError('Draft HTML exceeds the limit')
        if len(self.text()) > 100000:
            raise ValueError('Draft text exceeds the limit')
        from .templates import TEMPLATES
        if self.style.columns == 2 and TEMPLATES[self.template]['columns'] != 2:
            raise ValueError('This template supports a single column only; choose a column template first')
        if self.style.header == 'rail' and TEMPLATES[self.template]['layout'] != 'sidebar-left':
            raise ValueError('An identity sidebar requires a left-sidebar template')
        return self

    def text(self):
        return '\n\n'.join((s.title + '\n' if s.title.lower() != 'contact information' else '') + plain_text(s.html) for s in self.sections).strip()


class DraftSave(BaseModel):
    revision: int = Field(ge=1)
    content: DraftContent
    change_summary: str = Field(default='Manual edit', max_length=200)
    applied: list[str] = Field(default_factory=list, max_length=100)
    rejected: list[str] = Field(default_factory=list, max_length=100)


class RewriteRequest(BaseModel):
    resume_id: str
    section_id: str
    revision: int = Field(ge=1)
    original: str = Field(min_length=1, max_length=12000)
    action: Literal['Improve wording', 'Make it more professional', 'Make it more concise', 'Fix grammar', 'Achievement-oriented bullets', 'Improve clarity', 'Suggest measurable impact', 'ATS readability', 'Align with job description', 'Generate summary', 'Improve skills presentation', 'Stronger action verbs']
    job_description: str = Field(default='', max_length=15000)
    ai_consent: bool = False


class RewriteOutput(BaseModel):
    model_config = {'extra': 'forbid'}
    original: str = Field(min_length=1, max_length=12000)
    suggested: str = Field(min_length=1, max_length=12000)
    notes: list[str] = Field(max_length=10)


def seed_content(text: str):
    sections = [{'id': 'contact', 'title': 'Contact information', 'lines': []}]
    for line in text.splitlines():
        standard = heading_key(line)
        if standard:
            sections.append({'id': f'{standard}-{len(sections)}', 'title': line.strip().strip(':'), 'lines': []})
        else:
            sections[-1]['lines'].append(line)
    return DraftContent(sections=[Section(id=s['id'], title=s['title'], html=text_to_html('\n'.join(s['lines']))) for s in sections]).model_dump()
