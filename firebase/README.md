# Ordinary Cloud Firestore — no billing account

**User requirement:** use normal Cloud Firestore for application data, remain on the free
Spark plan, and do not attach a billing account or create paid services.

## What is now working

- Project **nitre-d8cdd** / **Nitre**, default Firestore Native database in **nam5**.
- The running local FastAPI app now uses Firestore as its **primary structured database**.
  This is not merely a Firebase config or a score-only mirror.
- Migrated **212 existing records** atomically and verified every record by reading it back:
  33 resumes, 30 ATS/job analyses, 14 editor drafts, 36 editor versions, 57 text versions,
  3 builder drafts, 7 conversion jobs, 7 library documents, 24 source metadata rows and 1 user.
- The original SQLite database was not changed or deleted. A private SQLite backup was created
  under the ignored `backend/private-storage/migration-backups/` directory before migration.
- Existing Firestore default-deny browser rules were inspected and left unchanged. An anonymous
  read probe returned **403 PERMISSION_DENIED**. Only the authorized backend uses IAM access.
- A final live check confirmed **billing remains disabled and no billing account is attached**.
- Settings shows the active provider/project, and `/api/health` reports `database_backend: firestore`.

## Data layout (visible in Firebase console)

Open [Firestore data](https://console.firebase.google.com/project/nitre-d8cdd/firestore).
Application collections are nested below **formiqo / v1**:

- `formiqo_resumes`: extracted text, metadata, ownership, expiry.
- `formiqo_analyses`: ATS totals, category checks, job-description matching and evidence.
- `formiqo_editor_drafts`, `formiqo_editor_versions`, `formiqo_resume_versions`.
- `formiqo_builder_drafts`, `formiqo_conversion_jobs`, `formiqo_documents`.
- `formiqo_users`, `formiqo_auth_sessions`, `formiqo_auth_tokens`.
- `formiqo_source_documents`: original-upload **metadata**, not file bytes.

Passwords remain salted hashes; session/recovery secrets are stored as hashes, not plaintext.
Never open these collections to browser reads just to make a UI demo work. The existing
application authorizes every API request and download using its HttpOnly cookie sessions.

## Scope: data storage, not free Python hosting

Firestore stores **structured data**. It does not run FastAPI, Chromium, Tesseract or conversion
workers. PDF/DOCX/image input and output files remain in private backend file storage; binary
files were not split across Firestore documents to work around file-hosting limits.

No Cloud Run, Cloud Functions, Cloud SQL, SQL Connect or Cloud Storage bucket was provisioned.
The Python backend is running locally. Vercel is not connected to a public backend yet, so this
is **not a completed public deployment**. A separately hosted Python backend with durable file
storage is still required if the app must work when this computer is offline.

## Implementation

- [persistence.py](../backend/app/persistence.py) defines explicit record queries, conditional
  changes and parent/child lookups. SQL remains available as an optional local provider.
- [firestore_store.py](../backend/app/firestore_store.py) uses the official Python Firestore SDK
  and real native transactions. It never evaluates SQL or loads a database into a SQL emulator.
- Transaction update-time checks protect concurrent saves, revisions, one-use tokens and
  parent ownership. Unique email/library-job references are reserved in the same transaction.
- Indexed owner/parent/equality filters select candidates. Remaining filtering/sorting happens
  within that candidate set. These are intentionally small-workspace queries, not full-text
  search or a large-scale reporting engine; large per-owner lists still cost document reads.
- Query and batch guards bound oversized requests. Large structured records use a compressed
  payload with scalar query fields retained, or fail explicitly; content is never truncated.
- Free quota exhaustion returns an error; it does not enable billing or silently fall back to SQL.
- Firestore cleanup scans run every 15 minutes instead of every minute. Expiry checks on requests
  remain immediate. Billing-dependent TTL is not enabled.

## Configuration

A private, Git-ignored local `backend/.env` selects Firestore. Reproduce the setup with:

```dotenv
DATABASE_BACKEND=firestore
FIREBASE_PROJECT_ID=nitre-d8cdd
FIREBASE_DATABASE_ID=(default)
FIREBASE_NAMESPACE=v1
STORAGE_DIR=./private-storage
# Optional private local ADC path; never put credentials in the repository:
# FIREBASE_CREDENTIALS_FILE=/absolute/private/path/google-credentials.json
```

Use Google Application Default Credentials (ADC) or the optional private credentials-file path.
The local developer credential is stored outside the workspace with mode 0600. The user-supplied
Firebase **browser API key is not a server credential**, is not needed by the Python database
client, and was not copied into source. Use a least-privilege service account on a hosted backend;
do not upload a developer OAuth credential into Vercel frontend variables.

`DATABASE_BACKEND=sql` retains SQLite/PostgreSQL support. Switching providers does not synchronize
them automatically; after migration new writes go only to the selected provider. Do not switch
back to an older SQLite snapshot and claim it contains later Firestore edits.

## Migration and rollback

The [migration command](../backend/app/migrate_firestore.py) defaults to a **dry run**:

```sh
cd backend
python -m app.migrate_firestore --project nitre-d8cdd
python -m app.migrate_firestore --project nitre-d8cdd --apply
```

It validates source ownership and record sizes, skips expired/orphaned rows, backs up SQLite,
refuses conflicting existing target records, commits atomically and verifies all records in a
fresh read. It is idempotent for an unchanged source. A newer target is never overwritten by a
rerun. The source remains intact if migration fails. Current atomic migration has a conservative
400-record application guard; a larger migration needs explicitly reviewed batches.

For rollback after new Firestore edits, export/migrate the **current** Firestore data first.
The original SQLite backup only reflects the migration-time state.

## Tests and evidence

- Backend: **184 passed**, including **11 Firestore/size/migration tests**.
- Frontend: **42 passed**, production build and typecheck clean.
- All seven real Chrome browser suites passed against the **live Firestore-backed app**:
  ATS upload/scoring, editor, builder, conversion/accounts, premium gallery/import,
  selected-text writing/crop and score records/export.
- Fixed slow-cloud initialization races: deduplicated the cookie-setting config request and
  gated private pages until workspace identity is established; cleared stale save notices.
- The continuation test now waits for the actual save response/revision instead of assuming
  Word/HTML normalization always leaves it at revision 4.
- GitHub CI includes Java 21 + a **demo project** Firestore emulator run (no live credentials).

Run emulator checks without touching the real database:

```sh
# Java 21+, Node 22+, Python dependencies installed
npx firebase-tools@15.34.1 emulators:exec --project demo-formiqo \
  --config firebase/emulators.json --only firestore \
  "cd backend && python -m pytest -q tests/test_firestore.py"
```

The checked-in rules are **emulator-only**, not a production rules deployment. Existing project
rules were not replaced. Live browser tests create/delete synthetic documents; no user accounts
or documents are deliberately exposed in screenshots or logs.

## Free-tier limitations

[Official Firestore quotas](https://firebase.google.com/docs/firestore/quotas) include a 1 GiB free
stored-data quota and daily operation quotas. The app can stop saving when the free quota is
exhausted; Spark is not unlimited storage. Monitor usage in Firebase. No auto-upgrade or paid
resource creation is implemented.
