# Formiqo — One Platform, Every Document

A working React/Vite/TypeScript frontend and FastAPI/SQLAlchemy backend. The original
project directory, database names and guest cookie remain compatible with the earlier ResumeAI build.
No random scores, fake conversions, invented activity or frontend API secrets.

For GitHub and Vercel hosting, see [GitHub + Vercel setup](GITHUB-VERCEL.md).
Vercel serves the frontend; persistent backend/database hosting is required separately.

## Start here

- Application: **http://localhost:5173**
- ATS checker: **/app/checker**
- Resume editor: **/app/editor**
- Guided builder: **/app/builder**
- Job matcher and reviewed tailored copies: **/app/matcher**
- Document converter: **/app/converter**
- Unified library: **/app/documents**
- Conversion history: **/app/history**
- Score records (every ATS / job-match score, with Excel/CSV/JSON download): **/app/records**
- Accounts, sessions, recovery and deletion: **/app/settings**
- Help/privacy: **/app/help**, **/app/privacy**

## Implemented capabilities

### ATS checker

Validated PDF/DOCX/UTF-8 TXT uploads, drag/drop and real upload progress, bounded background extraction,
editable text preview, original comparison, manual save and versions. Scans use Tesseract when installed.
Six transparent configurable categories total exactly 100 points; individual checks and evidence explain the result.
**Rubric 2.0** grades evidence rather than "appears once": the share of statements that lead with an action verb, give
context and state verified scale; concrete versus generic skills; vocabulary depth and length. Job mode weights each JD
term by where it appears (required 3, responsibilities 2, preferred 1, plus repetition/title) from a published
skills/tools lexicon with aliases (Postgres → PostgreSQL, CI/CD), technical tokens and repeated phrases. It reports
required-term gaps, where each match appears (experience/projects vs. skills only) and weighted coverage. Results
from rubric 1.x and 2.0 are never compared with each other.
General or job-specific analysis, supported findings/priorities, strengths, keyword overlap, Recharts visualization,
JSON downloads and genuine score recalculation/comparison. Optional consent-gated semantic AI feedback is separate from numerical scoring.

### Resume editor

TipTap rich text, bold/italic/underline, lists, safe hyperlinks, selection copying and text undo/redo.
Desktop three-panel layout and compact mobile panel controls. Add/remove/reorder sections,
word counts, opt-in 8-second autosave, explicit save, original comparison, reset-to-saved and version restore.
Optimistic revision checks prevent silent overwrites; source hashes detect checker/builder divergence.
Twelve writing actions use a configured LLM service and explicit consent. Original/suggested comparison,
edit/regenerate/reject/apply, factual confirmation and placeholder blocking protect the draft.
Real validated PDF/DOCX exports and actual PDF preview. Selected builder template remains attached during editing.

### Resume builder

Ten guided steps from contact through export; no fabricated applicant data is prefilled.
Repeatable work/education/project/credential entries, dates/current flags, custom sections and reordering.
Optional sections can be skipped. Save/reopen/autosave, safe links, sanitized live content preview and actual PDF preview.
Five single-column templates: Classic ATS, Modern Professional, Technical Resume, Minimalist and Experienced Professional.
Actual exports use each template’s typography, margins, spacing and heading color.
A name, contact channel and substantive resume section are required for export; incomplete drafts can be saved.
Newer editor/checker content is preserved; the builder offers a separate copy instead of overwriting it.

### Job matcher and safe tailored drafts

Dedicated resume selection/upload, target title/company and JD inputs.
Explicit term/skill relevance score, supported resume evidence, candidate gaps requiring confirmation,
and heading/clause-aware required/preferred/responsibility grouping (heuristic, not a qualification verdict).
Full ATS result links and optional consented semantic feedback.
Tailored previews highlight section movements. Confirming creates a separate draft and preserves the source.
**Safe tailoring deliberately reorders existing verified sections without changing their words.** It does not
invent skills, employers, dates or metrics. Use the editor for separately reviewed wording changes.
Tailored copies export through the existing PDF/DOCX editor workflow.

### Score records

Every saved ATS check and job match is listed at **/app/records** exactly as it was scored: ATS score, job-match
score, weighted term coverage, required terms found, findings and the six category scores. Search, filter by type or
resume, sort, expand a row for the breakdown, open the full report or delete a record. **Excel** (records, summary and
about sheets), **CSV** (formula-injection safe) and **JSON** (with findings and term evidence) exports are generated
by the API from the same rows. Records come from the existing `analyses` table, so nothing is duplicated, and they
expire with their resume.

### Page fit for PDF and Word

When only a short tail spills onto a new page, the canvas tightens spacing in bounded steps (body text never
below 9 pt) so it fits on fewer pages, and says so. Word exports reuse the same measured fit and set explicit
spacing instead of python-docx defaults, so PDF and DOCX agree on page count. Turn it off per document with
`style.auto_fit=false`. PDF-to-Word uses the column-aware reader and the source's page size, margins and type.

### Document converter and history

One **Document Converter** holds every tool: All, PDF, Images and Word & text tabs (the former separate PDF Tools
and Image Tools pages redirect here). Capability-driven supported matrix, upload validation, ordered mixed-image batches, page range/resolution,
paper/orientation/margins, private asynchronous jobs with polling, milestone progress, real outputs,
actual sizes/duration, warnings, individual page downloads and ZIP bundles. Inputs are removed after processing.
Failed jobs carry actionable errors; expired/unauthorized downloads are denied. History reopens retained outputs
and deletes jobs plus associated files/library records. Interrupted jobs are marked failed on restart and require re-upload.

Current built-in conversion matrix:

| Input | Outputs |
| --- | --- |
| PDF | DOCX, TXT, JPG, PNG (individual pages + ZIP) |
| DOCX | PDF, TXT, sanitized HTML |
| TXT | DOCX, PDF |
| JPG/JPEG | PNG, PDF, WEBP when Pillow supports it |
| PNG | JPG, PDF, WEBP when Pillow supports it |
| WEBP, when supported | JPG, PNG, PDF |
| HTML | TXT, PDF without script/CSS/remote-resource execution |
| PPTX/XLSX, conditional | PDF only with explicitly enabled LibreOffice and successful bubblewrap sandbox preflight |

**Fidelity limitations:** PDF-to-DOCX reconstructs text, basic emphasis/headings and detectable tables in page order;
columns, diagrams, signatures and complex layouts may need manual cleanup. DOCX-to-PDF is a disclosed basic-content
reconstruction, not faithful Office rendering. HTML is sanitized/reconstructed without CSS or network requests.
Image aspect ratios and chosen order are preserved. All outputs are opened/validated before completion is recorded.
Legacy **DOC is not DOCX and is not accepted**; export it as macro-free DOCX or PDF first.
OCR is required for scanned PDF text reconstruction. Input/output/page/pixel limits apply.

### Accounts and persistent workspaces

Optional registration/login/logout, salted scrypt passwords, opaque hashed server-side sessions,
session rotation/list/revoke-other-sessions, SMTP-gated one-time password reset and email verification,
optional required verification, and password-confirmed account/data deletion.
Guest tools remain available when allowed. Moving guest documents into an account requires explicit consent
at registration/sign-in; old guest URLs then lose access. Account documents persist in the configured durable
DB/volume and reopen in another signed-in browser. No tokens or documents are stored in localStorage.
Default retention: **24 hours for guests**, **365 days for account documents**, configurable. Exact expiry is shown.
Retaining account documents does not retain original upload binaries; extraction and structured versions remain.
Email delivery is never claimed when SMTP is missing or fails.

### Library, dashboard and contextual assistant

Search/filter/paginate actual resumes and converted files; open, rename, analyze appropriate resumes,
download and delete associated records/files. Dashboard actions link to working tools. Actual analyses,
saved versions and conversion events form recent activity. Usage counters reflect this API instance’s real
per-IP buckets and explicitly disclose shared-network/restart limits.
The assistant is embedded in editor and analysis pages, uses saved authorized context, accepts custom questions
and suggested prompts, cites grounded passages and offers schema-validated proposals when AI is consented/configured.
Without AI it provides a **clearly labeled local rubric review**, not a fake LLM conversation.
Proposals require review and explicit apply; rejection changes no content. Stale revisions/placeholders block application.

## Local development

Requirements: **Node 22.12+**, **Python 3.13+**. Use a normal Python installation rather than a hardened
application-bundled interpreter that blocks third-party native extensions.

```sh
# Terminal 1 — backend
cd resumeai/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

```sh
# Terminal 2 — frontend
cd resumeai/frontend
npm ci
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to **http://127.0.0.1:8010**.
Override the development API with `RESUMEAI_API_URL=http://127.0.0.1:PORT npm run dev`.
Use the exact allowed origin; localhost and 127.0.0.1 differ. FastAPI docs: **http://127.0.0.1:8010/docs**.
SQLite is a local-only fallback; Compose uses PostgreSQL. No key is needed for local scoring, building,
editing, safe tailoring or built-in conversion.

Optional native OCR:

```sh
# macOS / Homebrew
brew install tesseract
# Debian / Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

English OCR is used at 150 dpi. Mixed text/image pages can escape scan detection; review extraction.

Selectable PDFs use a **column-aware reading order** ([pdf_layout.py](backend/app/pdf_layout.py)): a validated gutter
is read one column at a time (right-aligned dates are not mistaken for a column), label-rail headings are placed before
their content, wrapped lines and list items are rejoined, and page numbers and repeated running headers are excluded
and reported. Every gallery template export round-trips to identical section text in tests. Third-party layouts with
overlapping text boxes, rotated text or tables may still need review against the retained original.

## AI, email and Office configuration

Backend environment examples are in [backend/.env.example](backend/.env.example).
Set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` for an OpenAI-compatible JSON-capable chat/completions service.
Consent disclosure names the provider. Requests send selected text/questions, saved resume context up to 30,000
characters, and optional JD up to 15,000. Credentials are backend-only; URLs reject embedded credentials/query secrets.
Provider retention/region/consent obligations must be reviewed. Schema/citation/numeric guards reduce risk but **cannot
prove every semantic claim or defeat every prompt injection**. Users must verify proposed facts.

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` and `PUBLIC_URL`
for real email delivery. Enable `REQUIRE_EMAIL_VERIFICATION=true` only after SMTP works.
One-use email tokens expire after one hour and live in URL fragments, not HTTP query strings or API responses.
Without SMTP, accounts work with verification optional, but reset/verification actions return an honest unavailable error.

The container explicitly installs Tesseract, LibreOffice Writer/Impress/Calc, fonts and bubblewrap.
`OFFICE_ENABLED=false` by default. Optional PPTX/XLSX conversions need a Linux host that supports unprivileged
no-network namespaces; the preflight must succeed before options appear. Do not weaken the main container with
broad privileges just to expose Office options. Validate representative outputs on an appropriately isolated worker host.
Native OCR, actual SMTP, live LLM calls, Docker/PostgreSQL and optional Office paths were **not verified on this host**.
Built-in conversions and the absence/error paths were verified; advanced providers use explicit test mocks.

## Docker, migrations and production

```sh
cd resumeai
cp .env.example .env
# Replace POSTGRES_PASSWORD with a long random URL-safe password.
docker compose up --build
```

Open **http://localhost:8080**. Private named volumes hold PostgreSQL and conversion output storage.
Only the frontend is exposed on loopback. Backend runs unprivileged with dropped capabilities,
no-new-privileges and CPU/memory/PID limits. Two native slots are shared by extraction and conversion.
See [DEPLOYMENT.md](DEPLOYMENT.md) for HTTPS, secrets, durable storage, migrations, monitoring and release gates.

SQL migrations are additive and preserve earlier guest records:

```sh
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/001_initial.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/002_resume_editor.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/003_resume_builder.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/004_accounts_and_conversions.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/005_retained_sources.sql
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f backend/migrations/006_score_records.sql
```

Use a regular PostgreSQL DSN with psql, not SQLAlchemy’s `+psycopg` prefix. Apply only migrations not already applied.
Startup `create_all` creates missing tables but does not alter existing columns. Back up before migrations.

## API overview

All request schemas, constraints/status codes and endpoints are documented in FastAPI OpenAPI.

- Authentication: `/api/auth/register`, `/login`, `/logout`, `/refresh`, `/me`, `/sessions`, `/revoke-other-sessions`, `/forgot-password`, `/reset-password`, `/resend-verification`, `/verify-email`, `/account`.
- Resume upload/list/get/patch/delete, text versions/download: `/api/resumes` and children.
- Analysis/results/compare/reanalysis: `/api/ats`.
- Structured editor persistence, versions, preview import and PDF/DOCX export: `/api/editor/{id}`.
- Guided creation/templates/preview/list/save/export: `/api/builder`.
- Writing actions, matching, tailoring, contextual questions and explicit proposal application: `/api/ai`.
- Capabilities, queued jobs/polling/private downloads/delete/history: `/api/converter`.
- Unified owned library/search/rename/delete: `/api/documents`.
- Actual activity/usage: `/api/activity`, `/api/usage`.
- Database/cleanup health: `/api/health`.

## Security and limits

- Extension/MIME/signature validation, macro rejection, archive expansion limits, UTF-8 checks, randomized internal filenames and private directories.
- Request-body limits before multipart parsing, pixel/page/text/output bounds and subprocess CPU/memory/file/time limits on Linux.
- Separate-process native parsing; one shared two-slot budget. Job queue sizes and per-IP endpoint buckets restrict work.
- Office child: no-network bubblewrap namespace with cleared environment and restricted binds. Python parsing itself is **not a complete OS/no-network sandbox**; public hostile workloads need a separately restricted worker environment.
- Opaque HttpOnly SameSite=Strict sessions, trusted origins/hosts, Secure cookies for HTTPS, ownership and expiry on every private download/record operation.
- Server-side HTML allowlist; no document scripts/macros executed or remote HTML resources loaded. AI text is rendered/inserted safely.
- Password hashing and session/token digests; password resets revoke sessions. SQL bound parameters are hidden in exceptions/logging.
- Original sources, OCR scratch and retained output cleanup; deletion removes related active records. Janitor failures retry and are visible in health checks.
- API responses are no-store. Production Nginx provides CSP, nosniff and no-referrer. No document text/API keys/passwords are deliberately logged.
- Default guests/account retention is explicit; expiry is not silently extended by edits. Backups require separate aligned retention/deletion policies.
- Saves use revision/source checks. Normal links and full-page exits warn about unsaved edits; browser-history navigation is not a complete recovery system. Save before leaving.
- Current queue/limiter are **single-instance**. Do not scale API workers until shared queue/locking/rate infrastructure is added. Interrupted jobs require safe re-upload rather than automatic replay.

## Tests and evidence

```sh
cd resumeai/backend
source .venv/bin/activate
python -m pytest -q
cd ../frontend
npm test
npm run build
npx playwright install chromium
# Start both servers before browser tests:
npm run test:e2e
# Or use existing Chrome:
CHROME_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:e2e
```

Current backend suite: **173 tests**. Frontend unit/component suite: **40 tests**. Seven browser e2e suites. Production build and actual
browser workflows cover checker, editor, builder, conversion/ZIP/ordered mixed images, account claiming,
sign-in/out isolation/persistence, library rename/filter, history, matcher/tailored copies, local assistant,
unavailable SMTP, account deletion and responsive layouts. Actual conversion outputs are opened, not merely status-checked.
OCR/SMTP/live-AI control-flow tests use explicit mocks. Optional Office conversions are not asserted as tested here.
Axe checks on tested pages reported zero steady-state WCAG A/AA violations; this is not a full accessibility certification.
Synthetic screenshots/files live in the ignored frontend test-results folder. CI is supplied in
[formiqo-ci.yml](../.github/workflows/formiqo-ci.yml); a hosted CI run was not performed here.
Security audits: `npm audit`, `pip-audit -r requirements.txt`; rerun as advisories evolve.

## Architecture

Frontend routes are lazy-loaded; shared primitives use Radix/CVA shadcn-style source, Lucide icons, RHF/Zod,
Recharts and TipTap. Typed API helpers keep business logic out of components where practical.
Backend separates scoring, extraction, conversion/worker execution, AI review/intelligence, auth, storage,
library/activity, builder/editor schemas, exports and database access. No duplicate file bytes in the database.
PostgreSQL stores accounts, session/token digests, resume/analysis/version/builder records, conversion metadata
and conversion-library references. Private output files use authorized serving paths, never public static URLs.

Remaining release gates are configuration/operations and fidelity validation, not fake placeholder modules:
live provider/email/OCR/optional Office testing, production infrastructure hardening, deployment/restore drills,
and external scoring calibration. No employment guarantee, security certification or universal ATS fidelity claim is made.
Review PyMuPDF’s AGPL/commercial license and provider terms before commercial deployment.
