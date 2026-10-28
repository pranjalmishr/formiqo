import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, DateTime as SQLDateTime, ForeignKey, Text, JSON, Integer, Boolean, Index
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


class DateTime(TypeDecorator):
    """Keep UTC offsets in API timestamps, including SQLite development reads.

    SQLite drops timezone metadata from native DATETIME values; treating those
    UTC values as browser-local time otherwise misreports save/expiry times.
    The stored SQL type is unchanged, so existing databases need no alteration.
    """
    impl = SQLDateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None: return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None: return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Resume(Base):
    __tablename__ = 'resumes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(180))
    original_format: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text, default='')
    original_text: Mapped[str] = mapped_column(Text, default='')
    extraction: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Analysis(Base):
    __tablename__ = 'analyses'
    # Score records list per owner, newest first (migrations/006_score_records.sql).
    __table_args__ = (Index('ix_analyses_owner_created', 'owner', 'created_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    resume_id: Mapped[str] = mapped_column(ForeignKey('resumes.id', ondelete='CASCADE'), index=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    overall_score: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSON)
    scoring_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ResumeVersion(Base):
    __tablename__ = 'resume_versions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    resume_id: Mapped[str] = mapped_column(ForeignKey('resumes.id', ondelete='CASCADE'), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EditorDraft(Base):
    __tablename__ = 'editor_drafts'
    resume_id: Mapped[str] = mapped_column(ForeignKey('resumes.id', ondelete='CASCADE'), primary_key=True)
    content: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_hash: Mapped[str] = mapped_column(String(64))
    applied: Mapped[list] = mapped_column(JSON, default=list)
    rejected: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class EditorVersion(Base):
    __tablename__ = 'editor_versions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    resume_id: Mapped[str] = mapped_column(ForeignKey('resumes.id', ondelete='CASCADE'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    change_summary: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BuilderDraft(Base):
    __tablename__ = 'builder_drafts'
    resume_id: Mapped[str] = mapped_column(ForeignKey('resumes.id', ondelete='CASCADE'), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_hash: Mapped[str] = mapped_column(String(64))
    editor_revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class SourceDocument(Base):
    __tablename__ = 'source_documents'
    resume_id: Mapped[str] = mapped_column(ForeignKey('resumes.id', ondelete='CASCADE'), primary_key=True)
    format: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str] = mapped_column(String(180))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthToken(Base):
    __tablename__ = 'auth_tokens'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    purpose: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ConversionJob(Base):
    __tablename__ = 'conversion_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    source_filename: Mapped[str] = mapped_column(String(180))
    source_format: Mapped[str] = mapped_column(String(10))
    target_format: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    inputs: Mapped[list] = mapped_column(JSON, default=list)
    outputs: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DocumentRecord(Base):
    __tablename__ = 'documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('conversion_jobs.id', ondelete='CASCADE'), unique=True)
    filename: Mapped[str] = mapped_column(String(180))
    format: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(30), default='converted')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


engine = create_engine(settings.database_url, connect_args={'check_same_thread': False} if settings.database_url.startswith('sqlite') else {}, pool_pre_ping=True, hide_parameters=True)
Session = sessionmaker(engine, expire_on_commit=False)


def init_db():
    Base.metadata.create_all(engine)
    # create_all skips indexes on pre-existing tables; add the additive records index.
    from sqlalchemy import inspect
    if 'ix_analyses_owner_created' not in {index['name'] for index in inspect(engine).get_indexes('analyses')}:
        Analysis.__table__.indexes and next(index for index in Analysis.__table__.indexes if index.name=='ix_analyses_owner_created').create(engine, checkfirst=True)


def get_db():
    with Session() as db:
        yield db
