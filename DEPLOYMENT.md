# Formiqo deployment and release checklist

This repository supplies a working single-instance deployment, not a security certification.
A production release requires the configuration and operational checks below.

## Recommended topology

HTTPS ingress → frontend Nginx/static assets + same-origin `/api` proxy → one FastAPI instance → managed PostgreSQL.
Use a private durable encrypted volume for retained conversion outputs and scratch storage.
Original uploads are removed after processing; resume text/versions are in PostgreSQL.
Do not put retained outputs only on an ephemeral serverless filesystem.

The local [compose.yaml](compose.yaml) provides PostgreSQL, API and frontend with persistent named volumes.
The backend image explicitly installs Tesseract, fonts, LibreOffice components and bubblewrap.
Its native Python parsers are process-isolated with limits, but **not a complete no-network OS sandbox**.
For hostile multi-tenant production workloads, move native processing into a separately restricted worker environment
with no API/database/AI credentials and no unnecessary network access before opening public uploads.

## Local container path

```sh
cp .env.example .env
# Set a strong URL-safe POSTGRES_PASSWORD; never commit .env.
docker compose up --build -d
docker compose ps
curl --fail http://localhost:8080/api/health
```

The frontend binds `127.0.0.1:8080`; DB/API are internal. API health checks depend on database reachability.
Use `docker compose logs --tail=100 backend` for status/error-class diagnostics, never log document bodies.
The supplied container/Compose configuration was not built on the current host because Docker is unavailable.

## Production configuration

Set these through a secret manager/environment, not frontend code:

- `DATABASE_URL=postgresql+psycopg://...` with TLS as required by the managed database.
- `STORAGE_DIR` on a private encrypted durable volume, owned by the unprivileged API UID (10001 in the image).
- `ALLOWED_ORIGIN=https://your-domain.example` exactly; no wildcard credentials policy.
- `ALLOWED_HOSTS=["your-domain.example","backend"]` for the actual ingress host. Remove development hosts.
- `PUBLIC_URL=https://your-domain.example` for email links.
- `SECURE_COOKIE=true`, HTTPS termination, redirect HTTP to HTTPS and set HSTS at the trusted ingress.
- `ACCOUNTS_ENABLED`, `GUEST_ALLOWED`, `REQUIRE_EMAIL_VERIFICATION` for your product policy.
- `RETENTION_HOURS` (guest default 24), `ACCOUNT_RETENTION_DAYS` (default 365), `SESSION_DAYS` (default 30).
- `MAX_UPLOAD_MB`, `MAX_PAGES`, processing timeouts and per-IP rate limits consistent with capacity.

The Nginx upload cap is 11 MB by default, including multipart overhead. If raising backend limits, update ingress/Nginx limits too.
All frontend requests use relative `/api`; separate static hosting must proxy/rewrite that path and preserve private cookies.
A same-origin proxy is preferable to cross-site third-party cookies. Vite’s proxy is development-only.
Do not expose the private output directory through a static server or public object-storage bucket.

## AI configuration

`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` configure an OpenAI-compatible JSON-capable chat/completions provider.
Keep credentials in the backend. Plain service URLs must not contain credentials or query secrets.
Consent names the configured provider; review provider retention, processing region and legal basis before enabling.
Local scores, safe tailoring, conversions and building work without AI.
No live LLM call was verified here; use representative staging resumes and confirm schema/error behavior before release.
Automated grounding checks do not prove every AI statement true. Human approval remains mandatory.

## Email configuration

Set `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS=true`.
Use a real authenticated sender/domain with the provider’s DNS requirements. Test delivery to your own staging inbox.
`REQUIRE_EMAIL_VERIFICATION=true` requires SMTP; registration refuses an unconfigured verification requirement.
Password-reset/verification tokens are one-use, stored as digests, expire after one hour, and are sent in URL fragments.
They are not returned in API responses. Password reset revokes all sessions.
Without SMTP, the UI/API explicitly reports unavailability rather than claiming a message was sent.
The tests mock SMTP acceptance; real delivery was not verified on this host.

## OCR and optional Office engine

Tesseract English OCR is installed in the container. Verify a real scanned PDF and the corrected text preview in staging.
Native host development must install Tesseract itself; the application does not assume it exists.

`OFFICE_ENABLED=false` by default. To expose PPTX/XLSX-to-PDF, use an isolated Linux worker host supporting
unprivileged user/network namespaces and enable the flag only after reviewing its security policy.
LibreOffice and bubblewrap must be present; the sandbox preflight must succeed. The Office child has a cleared
environment, no network and restricted filesystem binds. Many container hosts disallow the required namespaces;
then the matrix hides Office options and the built-in conversions still work.
Do not grant broad privileges to the API container just to bypass a failed preflight.
Validate representative presentations/spreadsheets and output fidelity before public exposure.
These optional Office paths were not tested here. Legacy binary DOC remains deliberately rejected even when Office is installed.

## Database migration and backup

Take an encrypted backup before applying migrations. Apply only new migrations, in order:

```sh
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/001_initial.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/002_resume_editor.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/003_resume_builder.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/004_accounts_and_conversions.sql
```

Use a standard PostgreSQL DSN with psql (not SQLAlchemy’s `+psycopg` form).
The additive migrations preserve existing guest resumes/cookies. Startup `create_all` only creates missing tables;
it is not an alteration/migration engine. Test migration and restore on a staging copy before production.
Back up the database **and** retained output volume consistently. Test restoring owned downloads and session behavior.
Align backup retention with the privacy/deletion policy; active-data deletion cannot erase an immutable old backup by itself.
Managed PostgreSQL and migration/restore drills were not exercised on this host.

## Capacity and scaling

Keep **one API worker/instance** for this release. Queue tracking, native slot limits, usage counters and IP limits are process-local.
Extraction and conversion share two native slots. Each job has page/pixel/text/output/time limits.
Passwords have a separate two-slot hashing budget. Compose allocates 4 GB and two CPUs as a starting configuration,
not a measured throughput guarantee. Load-test actual workloads and set storage quotas/edge abuse controls.

Before horizontal scaling: shared rate limiting, durable external queue, distributed job claiming/locks,
independent restricted native workers, private shared/object storage and a separate cleanup scheduler are required.
Redis/Celery are not silently assumed or fabricated. Interrupted jobs are marked failed and require safe re-upload;
there is no ambiguous automatic side-effect replay.

## Health, cleanup and logging

- `/api/health` checks DB access and reports `cleanup_last_success`, `cleanup_error`, and degraded status on cleanup errors.
- The janitor runs every minute while the API runs and on startup; failures retry instead of silently stopping the task.
- Inputs/OCR scratch are removed after processing. Expired rows/outputs and orphan directories are cleaned.
- Alert on non-2xx health, degraded cleanup status, stale cleanup timestamp, disk/inode pressure, failed/interrupted jobs and 429 spikes.
- Logging configuration is in [backend/logging.json](backend/logging.json). It removes access-log query strings,
  avoids document-body logging, suppresses sensitive exception text and uses hidden SQL bound parameters.
- Use correlation IDs/status/error class for diagnostics. Do not enable SQL echo or payload logging for real resumes.
- External monitoring is not preconnected. Configure a private collector with request-body/cookie/header redaction and documented retention.
- Review errors using synthetic documents in staging rather than uploading sensitive production text to debugging services.

## Release verification

```sh
# Backend
python -m pytest -q
pip-audit -r requirements.txt
# Frontend
npm ci
npm test
npm run build
npm audit
npx playwright install chromium
# With both services running:
npm run test:e2e
```

The browser suite uses synthetic documents/accounts and writes ignored evidence under frontend/test-results.
Supplied CI runs tests/build/audits/browser workflows; no hosted CI/deployment execution is claimed here.
Before release, additionally verify:

1. Cross-account downloads, guest-claim consent, session revocation, reset/verification delivery and account deletion.
2. Real OCR, all enabled Office routes, complex tables/columns, multiple pages and output cleanup/fidelity.
3. HTTPS/cookies/hosts/origins/CSP, malformed inputs, resource/time/disk limits and monitored retention cleanup.
4. Mobile/keyboard/screen-reader behavior. Automated zero-violation checks are not a full accessibility audit.
5. Database/output-volume backup/restore, restart/interruption handling and deployment rollback.
6. External scoring calibration and product wording: estimates are not hiring decisions or employment guarantees.
7. PyMuPDF AGPL/commercial licensing, dependency notices and AI/email provider terms.
