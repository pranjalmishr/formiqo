from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class DraftPatch(BaseModel):
    text: str = Field(min_length=1, max_length=100000)


class AnalyzeRequest(BaseModel):
    resume_id: str
    text: str = Field(min_length=20, max_length=100000)
    job_description: str = Field(default='', max_length=30000)
    job_title: str = Field(default='', max_length=160)
    company: str = Field(default='', max_length=160)
    industry: str = Field(default='General', max_length=80)
    ai_consent: bool = False
    mode: Literal['general', 'job'] = 'general'


class Finding(BaseModel):
    id: str
    category: str
    section: str = 'Whole document'
    priority: Literal['critical', 'high', 'medium', 'low']
    title: str
    evidence: str
    why: str
    correction: str
    example: str | None = None
    requires_confirmation: bool = False


class Category(BaseModel):
    key: str
    label: str
    score: int
    maximum: int
    explanation: str
    checks: list[dict]


class SemanticObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category: Literal['experience', 'keywords', 'skills', 'grammar', 'clarity']
    evidence: str = Field(min_length=8, max_length=500)
    recommendation: str = Field(min_length=8, max_length=700)
    strength: bool


class SemanticResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    observations: list[SemanticObservation] = Field(max_length=10)


class CompareRequest(BaseModel):
    original_id: str
    updated_id: str
