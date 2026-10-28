"""Typed user-entered resume facts -> sanitized editor sections. No generated claims."""
import re
from html import escape
from typing import Annotated
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator
from .editor_content import DraftContent, Section
from .templates import TemplateKey

Short = Annotated[str, StringConstraints(max_length=180, pattern=r'^[^\n\r\t]*$')]
Long = Annotated[str, StringConstraints(max_length=12000)]
Date = Annotated[str, StringConstraints(pattern=r'^(?:|\d{4}(?:-(?:0[1-9]|1[0-2]))?)$')]
KEYS = ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'achievements', 'additional']


class Facts(BaseModel):
    model_config = {'extra': 'forbid'}

    @field_validator('*', mode='before')
    @classmethod
    def no_controls(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('Control characters are not allowed')
        return value


class Contact(Facts):
    name: Short = ''
    email: Short = ''
    phone: Short = ''
    location: Short = ''
    website: Short = ''
    linkedin: Short = ''

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address or leave it blank')
        return value

    @field_validator('website', 'linkedin')
    @classmethod
    def safe_url(cls, value):
        if value:
            from urllib.parse import urlsplit
            url = urlsplit(value)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or any(c.isspace() for c in value):
                raise ValueError('Use a full http:// or https:// URL without credentials')
        return value


class Dated(Facts):
    start: Date = ''
    end: Date = ''
    current: bool = False

    @model_validator(mode='after')
    def ordered(self):
        if self.current and self.end:
            raise ValueError('Clear the end date for a current entry')
        if self.start and self.end and self.end[:4] < self.start[:4]:
            raise ValueError('End date cannot be before start date')
        if len(self.start) == len(self.end) == 7 and self.end < self.start:
            raise ValueError('End date cannot be before start date')
        return self


class Experience(Dated):
    title: Short = ''
    employer: Short = ''
    location: Short = ''
    highlights: Long = ''


class Education(Dated):
    institution: Short = ''
    qualification: Short = ''
    details: Long = ''


class Project(Facts):
    name: Short = ''
    url: Short = ''
    technologies: Short = ''
    highlights: Long = ''

    _url = field_validator('url')(Contact.safe_url.__func__)


class Credential(Facts):
    name: Short = ''
    issuer: Short = ''
    date: Date = ''
    url: Short = ''

    _url = field_validator('url')(Contact.safe_url.__func__)


class Additional(Facts):
    title: Annotated[str, StringConstraints(max_length=100, pattern=r'^[^\n\r\t]*$')] = ''
    content: Long = ''


class BuilderData(Facts):
    contact: Contact = Field(default_factory=Contact)
    target_role: Short = ''
    summary: Long = ''
    experience: list[Experience] = Field(default_factory=list, max_length=15)
    education: list[Education] = Field(default_factory=list, max_length=10)
    skills: Annotated[str, StringConstraints(max_length=6000)] = ''
    projects: list[Project] = Field(default_factory=list, max_length=15)
    certifications: list[Credential] = Field(default_factory=list, max_length=15)
    achievements: Long = ''
    additional: list[Additional] = Field(default_factory=list, max_length=10)
    template: TemplateKey = 'classic-ats'
    section_order: list[str] = Field(default_factory=lambda: KEYS.copy(), min_length=8, max_length=8)
    step: int = Field(default=1, ge=1, le=10)

    @model_validator(mode='after')
    def bounded(self):
        if set(self.section_order) != set(KEYS):
            raise ValueError('Section order must contain each supported section exactly once')
        if len(self.model_dump_json()) > 220000:
            raise ValueError('Builder content exceeds the limit')
        # Validate the escaped/expanded output too; reject oversized generated
        # sections as a request-validation error, not an internal server error.
        to_content(self)
        return self


class BuilderSave(BaseModel):
    revision: int = Field(ge=1)
    data: BuilderData


def paragraph(value, bold=False):
    if not value.strip(): return ''
    return '<p>' + ('<strong>' if bold else '') + escape(value.strip()).replace('\n', '<br>') + ('</strong>' if bold else '') + '</p>'


def bullets(value):
    lines = [re.sub(r'^\s*[-•]\s*', '', line).strip() for line in value.splitlines() if line.strip()]
    return '<ul>' + ''.join('<li><p>' + escape(line) + '</p></li>' for line in lines) + '</ul>' if lines else ''


def link(label, url):
    return '<a href="' + escape(url, quote=True) + '">' + escape(label) + '</a>'


def dates(entry):
    return ' – '.join(part for part in [entry.start, 'Present' if entry.current else entry.end] if part)


def to_content(data: BuilderData):
    c = data.contact
    contact = paragraph(c.name, True) + paragraph(data.target_role)
    channels = [link(c.email, 'mailto:' + c.email) if c.email else '', escape(c.phone), escape(c.location)]
    if any(channels): contact += '<p>' + ' · '.join(v for v in channels if v) + '</p>'
    sites = [link(value, value) for value in [c.website, c.linkedin] if value]
    if sites: contact += '<p>' + ' · '.join(sites) + '</p>'
    sections = [Section(id='contact', title='Contact information', html=contact or '<p></p>')]
    content = {}
    content['summary'] = [('summary', 'Professional Summary', paragraph(data.summary))]
    exp = ''
    for item in data.experience:
        exp += paragraph(' | '.join(v for v in [item.title, item.employer] if v), True)
        exp += paragraph(' · '.join(v for v in [item.location, dates(item)] if v)) + bullets(item.highlights)
    content['experience'] = [('experience', 'Experience', exp)]
    edu = ''
    for item in data.education:
        edu += paragraph(' | '.join(v for v in [item.qualification, item.institution] if v), True)
        edu += paragraph(dates(item)) + paragraph(item.details)
    content['education'] = [('education', 'Education', edu)]
    content['skills'] = [('skills', 'Technical Skills', paragraph(data.skills))]
    projects = ''
    for item in data.projects:
        projects += '<p><strong>' + (link(item.name or item.url, item.url) if item.url else escape(item.name)) + '</strong></p>' if item.name or item.url else ''
        projects += paragraph(item.technologies) + bullets(item.highlights)
    content['projects'] = [('projects', 'Projects', projects)]
    credentials = ''
    for item in data.certifications:
        label = ' | '.join(v for v in [item.name, item.issuer, item.date] if v)
        if label: credentials += '<p>' + (link(label, item.url) if item.url else escape(label)) + '</p>'
    content['certifications'] = [('certifications', 'Certifications', credentials)]
    content['achievements'] = [('achievements', 'Achievements', bullets(data.achievements))]
    content['additional'] = [(f'additional-{index}', item.title or 'Additional Information', paragraph(item.content)) for index, item in enumerate(data.additional)]
    for key in data.section_order:
        for identifier, title, html in content[key]:
            if html:
                sections.append(Section(id=identifier, title=title, html=html))
    return DraftContent(sections=sections, template=data.template)


def export_issues(data: BuilderData):
    issues = []
    if not data.contact.name.strip(): issues.append('Add your full name in Contact information.')
    if not (data.contact.email.strip() or data.contact.phone.strip()): issues.append('Add at least one contact channel: email or phone.')
    if len(to_content(data).sections) < 2: issues.append('Add a summary or at least one relevant resume section before export.')
    for index, item in enumerate(data.experience):
        if any([item.title, item.employer, item.highlights, item.start, item.end, item.current]) and not (item.title.strip() and item.employer.strip()):
            issues.append(f'Complete the role and employer for experience entry {index + 1}, or remove it.')
    for index, item in enumerate(data.education):
        if any([item.institution, item.qualification, item.details, item.start, item.end, item.current]) and not item.institution.strip(): issues.append(f'Add an institution for education entry {index + 1}, or remove it.')
    for index, item in enumerate(data.projects):
        if any([item.url, item.highlights, item.technologies]) and not item.name.strip(): issues.append(f'Name project {index + 1}, or remove it.')
    for index, item in enumerate(data.certifications):
        if any([item.issuer, item.date, item.url]) and not item.name.strip(): issues.append(f'Name certification {index + 1}, or remove it.')
    for index, item in enumerate(data.additional):
        if item.content.strip() and not item.title.strip(): issues.append(f'Name additional section {index + 1}.')
    return issues
