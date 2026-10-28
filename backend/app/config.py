from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./resumeai.db'  # Local development only; Compose uses PostgreSQL.
    database_backend: Literal['sql','firestore'] = 'sql'
    firebase_project_id: str = ''
    firebase_database_id: str = '(default)'
    firebase_credentials_file: Path | None = None  # optional local ADC path; never a browser API key
    firebase_namespace: str = Field(default='v1', pattern=r'^[A-Za-z0-9_-]{1,80}$')
    storage_dir: Path = Path('./private-storage')
    max_upload_mb: int = Field(default=10, ge=1, le=25)
    max_pages: int = Field(default=30, ge=1, le=50)
    max_text_chars: int = Field(default=100000, ge=100, le=100000)
    extraction_timeout: int = Field(default=90, ge=10, le=120)
    retention_hours: int = Field(default=24, ge=1, le=72)
    guest_limit_per_hour: int = Field(default=30, ge=1, le=1000)
    secure_cookie: bool = False
    allowed_origin: str = 'http://localhost:5173'
    allowed_hosts: list[str] = ['localhost','127.0.0.1','backend','testserver']
    llm_base_url: str = 'https://api.openai.com/v1'
    llm_api_key: str = ''
    llm_model: str = 'gpt-4o-mini'
    accounts_enabled: bool = True
    guest_allowed: bool = True
    account_retention_days: int = Field(default=365, ge=1, le=3650)
    session_days: int = Field(default=30, ge=1, le=90)
    require_email_verification: bool = False
    public_url: str = 'http://localhost:5173'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from: str = 'Formiqo <noreply@example.com>'
    smtp_starttls: bool = True
    office_enabled: bool = False
    conversion_timeout: int = Field(default=120, ge=10, le=180)
    scoring_weights: dict[str, int] = {'structure': 20, 'keywords': 25, 'experience': 20, 'skills': 15, 'readability': 15, 'contact': 5}

    @field_validator('llm_base_url', 'public_url')
    @classmethod
    def safe_service_url(cls, value):
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use a plain http(s) service URL without credentials, query strings or fragments; keep secrets in separate environment variables')
        return value.rstrip('/')

    @field_validator('scoring_weights')
    @classmethod
    def validate_weights(cls, value):
        if set(value) != {'structure', 'keywords', 'experience', 'skills', 'readability', 'contact'} or any(v <= 0 for v in value.values()) or sum(value.values()) != 100:
            raise ValueError('Six positive scoring weights must total 100')
        return value


settings = Settings()
