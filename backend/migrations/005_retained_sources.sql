-- Premium upgrade: privately retained original resumes. Existing missing originals cannot be recovered.
BEGIN;
CREATE TABLE IF NOT EXISTS source_documents (
 resume_id VARCHAR(36) PRIMARY KEY REFERENCES resumes(id) ON DELETE CASCADE,
 format VARCHAR(10) NOT NULL,
 filename VARCHAR(180) NOT NULL,
 size INTEGER NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
);
COMMIT;
