-- Additive Formiqo Module 3 migration. Existing resumes/editor drafts are preserved.
BEGIN;
CREATE TABLE IF NOT EXISTS builder_drafts (
 resume_id VARCHAR(36) PRIMARY KEY REFERENCES resumes(id) ON DELETE CASCADE,
 data JSON NOT NULL,
 revision INTEGER NOT NULL,
 source_hash VARCHAR(64) NOT NULL,
 editor_revision INTEGER NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL
);
COMMIT;
