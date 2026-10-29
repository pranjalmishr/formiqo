# Formiqo progress tracker

Living status for the continuation work. Evidence is from commands actually run on this host;
nothing here is marked done without a passing test or an inspected output.

## How to run the checks on this host

The project's `backend/.venv` was created from the Designer-bundled interpreter, and macOS refuses
its native wheels (code-signature Team ID mismatch). Use `backend/.venv-local` (standalone CPython
3.13.18) or recreate `.venv` from a normal Python install. Node 22 lives at
`/private/tmp/resumeai-node/node-v22.15.0-darwin-arm64/bin`. `/tmp` is not durable, so install Node
22.12+ normally for long-term work.

## Audit baseline (2026-10-28)

| Area | State at audit | Evidence |
| --- | --- | --- |
| Backend suite | Working | 150 pytest tests passed. |
| Frontend unit + typecheck | Working | 40 vitest tests passed, `tsc -b` clean. |
| Template gallery | Working | 18 structurally different paginated HTML templates (single, label-rail, two-column, left/right sidebar, banded/masthead headers). |
| Visual studio editor | Working | Live canvas, section/entry reorder, design/type/layout inspector, reviewed AI writing, PDF/DOCX export. |
| Document tools | Working | 35 catalog tools (PDF edit/merge/split/compress/rotate/reorder/extract/delete/numbers/watermark, image resize/crop/rotate/compress, conversions). |
| Continuation e2e | **Failing** | Harness injected a DOM range that ProseMirror collapses, and waited on `<option>` visibility. Not wired into `npm run test:e2e`. |
| ATS calibration | **Defect** | Weak/mid/strong resumes scored 71/86/100; most checks were "appears once" booleans. |
| JD keyword extraction | **Defect** | A detailed payments JD gave 9 terms; Terraform, Kafka, Go, gRPC, CI/CD, PCI DSS, distributed systems were missed. Match 97. |
| Multi-column PDF import | **Defect** | Sidebar and main columns were interleaved; name landed in the summary; page numbers were imported as content. |
| Favicon | Minor | 404 on every page. |

## Tasks

| # | Priority | Task | Status |
| --- | --- | --- | --- |
| 1 | P0 | Fix continuation e2e harness | **Done.** Real press-drag selection; attached-option wait; suite added to `test:e2e`. |
| 2 | P0 | Column-aware PDF reading order for extraction + recreation | **Done.** `app/pdf_layout.py`; 18/18 template exports round-trip to identical section text; `tests/test_pdf_layout.py` (5). |
| 3 | P0 | ATS rubric 2.0 (graded evidence, concrete skills, weighted JD terms) | **Done.** `app/ats_terms.py`, `app/scoring.py`; weak/mid/strong now 53/62/97; payments JD now 19 weighted terms; `tests/test_ats_rubric_v2.py` (9). |
| 4 | P1 | Surface weighted JD evidence in the UI | **Done.** `KeywordCoverage` (results Job keywords tab) and matcher term rows; axe 0 violations; no overflow at 375 px. |
| 5 | P2 | Favicon | **Done.** `public/favicon.svg`. |
| 6 | P2 | README and test counts | **Done.** |

## Round 2 requests (2026-10-28)

| # | Request | Finding | Status |
| --- | --- | --- | --- |
| 7 | PDF Tools / Image Tools duplicate the Document Converter | Already in the nav before round 1: both were filtered views of the same 35-tool catalog. | **Done.** Removed from nav. Converter has All / PDF / Images / Word & text tabs (`?category=`); old URLs redirect. |
| 8 | DOCX formatting and multi-page overflow | Measured with LibreOffice as a Word-layout reference. Before: a ~200-word sample spilled onto page 2 on 7/18 studio PDFs and 9/18 DOCX files; PDF-to-Word gave +1 page on 6/8 inputs. | **Done.** Explicit Word spacing (python-docx defaults removed), fixed-layout zero-padding tables, a bounded spill-over fit shared by PDF and DOCX, and PDF-to-Word rebuilt on the column-aware engine with source page geometry. After: 18/18 templates are 1 page in both PDF and DOCX; PDF-to-Word matches the source page count on 8/8. `tests/test_page_fit.py` (6). |
| 9 | Premium resume builder | Preview was a 35% thumbnail that read as blank (plus a 422 on empty drafts); template step used fake line thumbnails and said "five templates". | **Done.** Hero with content-based progress ring, 10-step horizontal stepper with completion checks, form beside a large live page, empty-state page, real 18-template miniatures. |
| 10 | Records database for ATS / job-match scores with downloads | Scores were stored per analysis but had no list, filter or export view. | **Done.** `/app/records` + `/api/records`: summary cards, search, type/resume filters, sorting, expandable category breakdown, delete, and Excel/CSV/JSON export. Index `ix_analyses_owner_created` (migration 006). `tests/test_records.py` (3), `records.e2e.cjs`. |

Recovered regression during round 2: a replace in `conversion.py` removed `image`, `rgb`, `images_pdf`,
`office_pdf` and `validate_output`. They were restored verbatim from the original source (Designer's session
history) and covered by the existing conversion/document-tool suites (41 tests).

## Current verified state

- Backend: 195 passed (including Firestore and Vercel-specific checks). Frontend unit: 47 passed.
  `tsc -b` and `npm run build`: clean.
- Browser e2e against **https://formiqo-six.vercel.app** (Chrome): `e2e`, `editor`, `builder`,
  `remaining`, `premium`, `studio-details` and `records` all PASS.
- Word page counts were measured with LibreOffice 26.2 (in `/tmp`, measurement only, not an app dependency). Microsoft Word may differ by a line or two with different installed fonts.

## GitHub / Vercel publication request

- Both GitHub and Vercel are authenticated as `pranjalmishr`.
- Private repository [pranjalmishr/formiqo](https://github.com/pranjalmishr/formiqo) created.
  The additional OAuth `workflow` permission was approved. The source was pushed to `main`,
  and the remote commit matched local commit `61c3e56434df91babd05f7fb2ea3852dbb41eee3`.
  GitHub Actions started after the push; hosted CI was still in progress at verification.
- Vercel project [formiqo](https://vercel.com/pranjal-mishras-projects-52970ad6/formiqo) is now
  **Ready in production**. Repository root (`.`), Node 22.x, Python 3.12, frontend/dist static
  output and a same-project ASGI API replace the initial frontend-only deployment attempt.
- The initial missing `FORMIQO_API_ORIGIN` failure was real and is resolved. The old optional
  external-backend build helper is not the current deployment path.
- Hardened Git/Vercel exclusions for secrets, local databases and private documents. Added
  standalone repository CI under `.github/workflows/checks.yml`.
- Public frontend and Python backend are now hosted on Hobby; Firestore remains on Spark.
  See [GITHUB-VERCEL.md](GITHUB-VERCEL.md) for exact settings, verified features and limits.

## Firebase backend/database request

- User provided Firebase web config for **nitre-d8cdd**; its API key was not copied into source.
- Firebase CLI authenticated successfully; the active project and default Firestore Native
  database (`nam5`) were read back from the live APIs. Saved the project alias in `.firebaserc`.
- The user clarified **ordinary Firestore, no billing account**. Implemented native primary
  persistence with explicit record queries, atomic transactions, revision/unique-email/token
  protection and document-size guards. SQL remains available for local regression/rollback.
- Migrated 212 existing structured records atomically to `formiqo/v1` in `nitre-d8cdd`; every
  record was read back and compared. Backed up SQLite privately; source DB was not deleted.
- Switched the local app to Firestore through an ignored `.env`. ADC stays outside Git with
  mode 0600. The browser API key is not used as a server credential. Settings shows the provider.
- Existing default-deny Firebase rules unchanged; anonymous probe 403. Final billing check:
  **disabled, no billing account attached**. No Cloud Run, Functions, Cloud SQL or buckets created.
- Public Python hosting is now complete on Vercel, with private Vercel Blob for files. Backfilled
  30 legacy local files with SHA-256 read-back verification; all 36 active file references were
  checked available. Local originals/backups were retained. No paid Firebase services were created.
- Slower cloud requests exposed initialization/save-status races. Fixed duplicate guest-cookie
  initialization and stale save notices, added two frontend tests, and updated continuation e2e
  to await the actual save revision rather than assume v4 after markup normalization.
- Details: [firebase/README.md](firebase/README.md). CI now runs a demo-project Firestore emulator.

## Vercel Hobby bug-fix pass

- Verified the team is **Hobby** (active); no Pro upgrade or Google billing account was enabled.
- Created a private Blob store within Hobby allowances and configured restricted keyless Google WIF.
- Fixed missing /tmp startup directory, subprocess import paths, flat requirements parsing,
  native Chromium memory/disk/library startup, and cold-start input/output/preview restoration.
- Reduced cloud bundle from about 387 MB to 249 MB using native Chromium CDP instead of
  Playwright's 142 MB Node driver. Real PDF rendering preserves source tokens and measured page count.
- Streamed private downloads to avoid filling ephemeral cache; actual 5.9 MB PNG download verified.
- Fixed Firestore map ordering causing false builder unsaved-change prompts and immediately
  prepared merge workspaces producing null file-order entries. Five new frontend tests cover these.
- Added 11 backend Vercel regressions; all seven public-site browser suites pass on the final code.
- Daily authenticated cleanup cron is configured. Native parser environments exclude server secrets.
- Limits: 4 MB uploads, 20 pages, bounded invocation duration, provider free allowances. Live external
  AI/email and OCR/Office engines are not configured; no fake successes are shown.

## Next candidates (not started)

1. DOCX import: apply the same title cleanup/list merging, and read text boxes (`w:txbxContent`) in order.
2. Studio: surface the rubric-2.0 per-statement checks inline on the canvas (highlight statements lacking an action verb or scale).
3. Word export: sidebar background colours and card shading are simplified in Word; consider cell shading for left rails.
4. Calibrate rubric thresholds against a larger, consented set of real resumes (current fixtures are synthetic).
5. Score records: trend chart per resume across versions; DOCX-to-PDF remains unavailable without sandboxed LibreOffice.

## Log

- Reproduced the continuation failure, fixed the harness, suite PASS.
- Built the layout engine; verified with 18 template exports plus synthetic sidebar and single-column PDFs.
- Rubric 2.0: old/new results are not comparable (`scoring_version` 2.0); the compare endpoint already refuses mixed versions.
- Two e2e expectations depended on rubric 1.x behaviour. The hard-coded `-4 points` now asserts the real API delta.
