-- Formiqo remaining modules: additive PostgreSQL migration.
-- Existing guest resume ownership and data remain valid; claiming is explicit.
BEGIN;
CREATE TABLE IF NOT EXISTS users (
 id VARCHAR(36) PRIMARY KEY, name VARCHAR(120) NOT NULL,
 email VARCHAR(254) NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 verified BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash VARCHAR(64) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_auth_sessions_expires_at ON auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS auth_tokens (
 token_hash VARCHAR(64) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 purpose VARCHAR(20) NOT NULL, expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_tokens_user_id ON auth_tokens(user_id);
CREATE INDEX IF NOT EXISTS ix_auth_tokens_expires_at ON auth_tokens(expires_at);
CREATE TABLE IF NOT EXISTS conversion_jobs (
 id VARCHAR(36) PRIMARY KEY, owner VARCHAR(64) NOT NULL,
 source_filename VARCHAR(180) NOT NULL, source_format VARCHAR(10) NOT NULL, target_format VARCHAR(10) NOT NULL,
 status VARCHAR(20) NOT NULL, progress INTEGER NOT NULL,
 settings JSON NOT NULL, inputs JSON NOT NULL, outputs JSON NOT NULL, warnings JSON NOT NULL,
 error TEXT, error_code VARCHAR(40), duration_ms INTEGER,
 created_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ, expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_conversion_jobs_owner ON conversion_jobs(owner);
CREATE INDEX IF NOT EXISTS ix_conversion_jobs_status ON conversion_jobs(status);
CREATE INDEX IF NOT EXISTS ix_conversion_jobs_expires_at ON conversion_jobs(expires_at);
CREATE TABLE IF NOT EXISTS documents (
 id VARCHAR(36) PRIMARY KEY, owner VARCHAR(64) NOT NULL,
 job_id VARCHAR(36) NOT NULL UNIQUE REFERENCES conversion_jobs(id) ON DELETE CASCADE,
 filename VARCHAR(180) NOT NULL, format VARCHAR(10) NOT NULL, category VARCHAR(30) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_owner ON documents(owner);
COMMIT;
