-- Module 1 PostgreSQL baseline. Apply once to a fresh database with psql -v ON_ERROR_STOP=1.
-- The app's SQLAlchemy create_all also creates this baseline for local development.
-- Subsequent releases must add versioned, reviewed migrations; create_all does not alter tables.
BEGIN;
CREATE TABLE IF NOT EXISTS resumes (
 id VARCHAR(36) PRIMARY KEY,
 owner VARCHAR(64) NOT NULL,
 filename VARCHAR(180) NOT NULL,
 original_format VARCHAR(10) NOT NULL,
 text TEXT NOT NULL,
 original_text TEXT NOT NULL,
 extraction JSON NOT NULL,
 status VARCHAR(20) NOT NULL,
 error TEXT,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resumes_owner ON resumes(owner);
CREATE INDEX IF NOT EXISTS ix_resumes_expires_at ON resumes(expires_at);
CREATE TABLE IF NOT EXISTS analyses (
 id VARCHAR(36) PRIMARY KEY,
 resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
 owner VARCHAR(64) NOT NULL,
 overall_score INTEGER NOT NULL,
 result JSON NOT NULL,
 scoring_version VARCHAR(80) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analyses_resume_id ON analyses(resume_id);
CREATE INDEX IF NOT EXISTS ix_analyses_owner ON analyses(owner);
CREATE TABLE IF NOT EXISTS resume_versions (
 id VARCHAR(36) PRIMARY KEY,
 resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
 text TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resume_versions_resume_id ON resume_versions(resume_id);
COMMIT;
