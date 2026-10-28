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

- Backend: 173 passed. Frontend unit: 40 passed. `tsc -b` and `npm run build`: clean.
- Browser e2e (Chrome, live servers): `e2e`, `editor`, `builder`, `remaining`, `premium`, `studio-details` and `records` all PASS.
- Word page counts were measured with LibreOffice 26.2 (in `/tmp`, measurement only, not an app dependency). Microsoft Word may differ by a line or two with different installed fonts.

## GitHub / Vercel publication request

- Both GitHub and Vercel are authenticated as `pranjalmishr`.
- Private repository [pranjalmishr/formiqo](https://github.com/pranjalmishr/formiqo) created.
  The initial push was rejected for missing OAuth `workflow` scope; permission refresh requested.
- Vercel project [formiqo](https://vercel.com/pranjal-mishras-projects-52970ad6/formiqo) created
  and locally linked. Root `frontend`, Node 22.x and custom build settings were configured and
  read back via the authenticated Vercel API. No deployment targets exist yet.
- Added Vercel frontend Build Output API configuration with a build-time `FORMIQO_API_ORIGIN`
  edge rewrite, SPA routing, and tests. Local frontend tests: 40 passed; deployment tests: 4 passed;
  production and Vercel-output builds pass (the latter used an example origin, not a live backend).
- Hardened Git/Vercel exclusions for secrets, local databases and private documents. Added
  standalone repository CI under `.github/workflows/checks.yml`.
- The user confirmed there is **no hosted backend**. See [GITHUB-VERCEL.md](GITHUB-VERCEL.md).
  Source push awaits the workflow permission; production awaits a live persistent backend origin.
  No working application URL is claimed.

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
