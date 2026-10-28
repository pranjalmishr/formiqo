-- Score records view: list/filter/export saved analyses per owner, newest first.
-- No new table: records are read from the existing analyses table, so scores are never duplicated.
BEGIN;
CREATE INDEX IF NOT EXISTS ix_analyses_owner_created ON analyses (owner, created_at DESC);
COMMIT;
