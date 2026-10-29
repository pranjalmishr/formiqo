# Formiqo — deployed on Vercel Hobby

**Live website:** https://formiqo-six.vercel.app

**Private repository:** https://github.com/pranjalmishr/formiqo

**Vercel project:** https://vercel.com/pranjal-mishras-projects-52970ad6/formiqo

The website and FastAPI API are now deployed together. The earlier frontend-only
`FORMIQO_API_ORIGIN` requirement no longer applies to this production project.
Google/Firebase billing was not enabled and the Vercel team remains on **Hobby**.

## Actual architecture

- **Frontend:** React/Vite static assets, served by Vercel.
- **Backend:** [api/index.py](api/index.py), a Python ASGI function on Vercel.
- **Structured records:** ordinary Firestore/Spark in project `nitre-d8cdd`.
- **Private binaries:** the private `formiqo-private-files` Vercel Blob store in iad1,
  using Hobby's included, capped allowance. Blob URLs are not made public.
- **PDF export:** pinned Chromium 153, controlled by a lean Python DevTools client.
  It renders the same canonical HTML, fonts and pagination as the editor; this is
  not a generic-text export or a screenshot.
- **Google access:** short-lived Vercel OIDC -> Workload Identity Federation -> a
  dedicated `roles/datastore.user` service account. No Google private key or developer
  OAuth refresh credential is deployed. Trust is restricted to this team/project.
- **Retention:** daily Hobby cron at 04:00 UTC, authorized by a server-only secret.
  Owner/expiry checks deny access immediately; physical cleanup can happen later.

`/tmp` is only a disposable processing cache. Inputs needed by a prepared workspace,
completed outputs and retained originals are persisted before successful status is
committed. Cloud invocations complete bounded work before responding; they do not
rely on an always-running background thread or a durable in-process queue.

The existing local/Docker workflows remain available. `VERCEL_SERVERLESS=false`
keeps their normal asynchronous workers, private local files and periodic janitor.

## Vercel project settings — use repository root

| Setting | Current value |
| --- | --- |
| Root Directory | Repository root (`.`), **not `frontend`** |
| Framework preset | Other |
| Node | 22.x |
| Python | 3.12, pinned in [.python-version](.python-version) |
| Install | `npm ci && npm --prefix frontend ci` |
| Build | `npm run build` |
| Output Directory | `frontend/dist` |
| Region | iad1 |
| API maximum invocation | 300 seconds (Hobby ceiling) |

Root [vercel.json](vercel.json), [package.json](package.json) and [requirements.txt](requirements.txt)
are authoritative. The build stages Chromium assets from the pinned npm package.
The flat runtime requirements intentionally exclude Playwright's approximately
142 MB Node driver and PostgreSQL/test dependencies. The measured Python bundle
fell from about 387 MB to 249 MB.

The old frontend-only Vercel build helper remains an optional **external-backend**
configuration, not this project's deployment path. Do not reselect `frontend` as
Root Directory or `npm run build:vercel` as this project's Build Command: that would
restore the obsolete missing-backend-origin build failure.

## Server-side environment

Vercel holds the private Blob binding and cron secret; they are never in Git or
frontend `VITE_*` variables. Non-secret identity settings:

- `GCP_WIF_PROVIDER=projects/721926516617/locations/global/workloadIdentityPools/formiqo-vercel/providers/vercel`
- `GCP_SERVICE_ACCOUNT_EMAIL=formiqo-vercel@nitre-d8cdd.iam.gserviceaccount.com`
- Preview `FIREBASE_NAMESPACE=preview` isolates previews from production `v1`.

The entrypoint sets Firestore, private Blob, HTTPS cookies, accepted hosts and `/tmp`
storage defaults. Production API requests stay same-origin; no external proxy
hostname or local tunnel is required. Existing Firestore default-deny browser rules
were left intact. The optional [backend/.env.example](backend/.env.example) is for
local development; never upload the developer's actual environment or credentials.

## Failures fixed using actual deployment logs

1. Missing `FORMIQO_API_ORIGIN`: replaced the frontend-only deployment with a same-project API.
2. Vercel requirements parser rejecting an included file: flattened the root runtime manifest.
3. Missing upload directory when ASGI lifespan was not run: initialize the disposable cache explicitly.
4. Parser subprocesses missing installed imports: forward the runtime import path, but strip server secrets.
5. Chromium exhausting `/tmp`: removed Playwright's bundled Node runtime from the cloud function.
6. Graphics libraries/context startup failure: package Chromium's matching native assets and use CDP.
7. Prepared workspaces disappearing on cold starts: restore private files and create input/output/cache parents.
8. Builder falsely warning about unsaved changes: compare map values independently of Firestore key order.
9. Merge order becoming `[null, null]` before the first poll: normalize and validate complete file permutations.
10. Cold starts aborting another invocation's work: skip global recovery/janitor in the serverless entrypoint.
11. Large files filling the warm cache: stream private downloads and evict committed processing caches.

## Verification

- **195 backend tests**, including Firestore emulator and Vercel-specific cold-start/storage checks.
- **47 frontend tests**, production build and typecheck pass.
- **All seven Chrome suites passed on the actual public production origin**, covering
  ATS upload/scoring, matcher, editor, builder, PDF/DOCX export, conversion/ZIP,
  account claiming/isolation, library, import/reconstruction and score-record downloads.
- An actual 5.9 MB converted PNG was downloaded through the authenticated API.
- Backfilled and SHA-256 read-back verified **30 existing local private files** (2.5 MB).
  A separate check found **all 36 active file references** available in private Blob.
  Original local files/backups were retained.
- Accessibility checks on exercised pages reported zero A/AA violations; not a certification.
- Build success alone was not used as evidence that the application worked.

## Honest limits and optional services

- **Uploads: 4 MB total per request**, below Vercel's 4.5 MB request ceiling.
- **20 pages per document** in the cloud deployment. Larger/slow jobs may require
  smaller inputs. A platform-terminated invocation is not an automatically replayed job.
- Firestore Spark, Blob and functions have finite included allowances. Exhaustion can
  stop service; there is no automatic paid upgrade. Monitor both provider dashboards.
- Native Tesseract/LibreOffice are not installed in this Hobby runtime. Scanned OCR
  and Office-to-PDF options are explicitly unavailable, not simulated.
- External generative AI and recovery email require backend provider/SMTP credentials.
  They are not configured by this deployment. Deterministic ATS scoring, safe local
  matching, editing, building and supported conversions work without those services.
- Native document parsing is process-isolated and bounded, not a full hostile-code
  sandbox/security certification. Review isolation, abuse controls, licensing,
  backups and Hobby fair-use terms before a commercial or high-volume release.

## Re-deploy

From the repository root, with the same linked Vercel project:

```sh
npm ci
npm --prefix frontend ci
npm --prefix frontend test
npm run build
vercel deploy --prod
```

GitHub integration should keep using repository root. Do not force-push or overwrite
an existing Vercel project. Production cloud credentials remain in Vercel, not in a
locally committed deployment file.

Official references: [Python runtime](https://vercel.com/docs/functions/runtimes/python),
[function limits](https://vercel.com/docs/functions/limitations),
[Blob Hobby allowances](https://vercel.com/docs/vercel-blob/usage-and-pricing),
[Google OIDC federation](https://vercel.com/docs/oidc/gcp).
