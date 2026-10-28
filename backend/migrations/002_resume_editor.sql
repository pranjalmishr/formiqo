-- Formiqo Module 2 additive migration: existing guest sessions/resumes are preserved.
BEGIN;
CREATE TABLE IF NOT EXISTS editor_drafts (
 resume_id VARCHAR(36) PRIMARY KEY REFERENCES resumes(id) ON DELETE CASCADE,
 content JSON NOT NULL,
 revision INTEGER NOT NULL,
 source_hash VARCHAR(64) NOT NULL,
 applied JSON NOT NULL,
 rejected JSON NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS editor_versions (
 id VARCHAR(36) PRIMARY KEY,
 resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL,
 content JSON NOT NULL,
 change_summary VARCHAR(200) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_editor_versions_resume_id ON editor_versions(resume_id);
COMMIT;
