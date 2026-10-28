# GitHub + Vercel deployment

## Target and current status

- Requested GitHub account: [pranjalmishr](https://github.com/pranjalmishr).
- Created private repository: [pranjalmishr/formiqo](https://github.com/pranjalmishr/formiqo). The repository root is this
  Formiqo directory, not the surrounding Designer starter workspace.
- Vercel root directory: `frontend`.
- Both CLIs are authenticated as `pranjalmishr`. The additional GitHub `workflow` permission was
  approved and the source was pushed to `main`. The remote commit was read back and matched
  local commit `61c3e56434df91babd05f7fb2ea3852dbb41eee3` at verification.
- [GitHub checks](https://github.com/pranjalmishr/formiqo/actions) started after the push;
  no hosted-CI pass is claimed while the run is still in progress.
- Vercel project [formiqo](https://vercel.com/pranjal-mishras-projects-52970ad6/formiqo)
  was created and linked. Verified settings: root `frontend`, framework Other, Node 22.x,
  install `npm ci`, build `npm run build:vercel`, no Output Directory override.
- The user subsequently selected Firebase project **nitre-d8cdd** for the backend/database.
  Project access and a synthetic Firestore create/read/delete check succeeded. Billing is disabled,
  the specified storage bucket does not exist, and no Cloud Run backend is deployed. See
  [Firebase verification and remaining work](firebase/README.md). The app's relational database
  is not migrated by this project association. No paid resources were created.
  GitHub auto-deploy integration stays disconnected until a live backend origin is available.
- Do not paste access tokens into source or chat; use the CLIs' browser/device login.

## Hosting split (required)

Vercel serves the React app. The existing FastAPI backend uses long-running native conversion
workers, local private files, a cleanup loop and PostgreSQL. Do **not** deploy it as an ephemeral
Vercel Function: uploads, queued jobs and retained outputs would not be durable.

Deploy [backend/Dockerfile](backend/Dockerfile) to a persistent container host, with managed
PostgreSQL and a private volume. Keep a single API instance. The existing [compose.yaml](compose.yaml)
is available for a server deployment; see [DEPLOYMENT.md](DEPLOYMENT.md) for security and backup gates.
This change does not provision a paid container host or database.

On the backend set:

- `DATABASE_URL`: your PostgreSQL connection string (a backend secret, never a Vercel frontend variable).
- `STORAGE_DIR`: the mounted private volume directory.
- `PUBLIC_URL` and `ALLOWED_ORIGIN`: the actual production frontend HTTPS origin, exactly.
- `ALLOWED_HOSTS`: a JSON list containing the backend hostname and the actual forwarded frontend
  hostname if the ingress preserves it. Do not use `*`.
- `SECURE_COOKIE=true`.
- AI/email credentials only on the backend, when those services are enabled.

## Vercel project

Import the GitHub repository into Vercel with **Root Directory = frontend**. Framework preset is
**Other** because the project emits Vercel's Build Output API itself. The checked-in
[frontend/vercel.json](frontend/vercel.json) runs `npm ci` and `npm run build:vercel`.
Do not set an Output Directory override; the output is `.vercel/output`.

Set the build environment variable **FORMIQO_API_ORIGIN** to the public HTTPS origin of the running
backend, for example `https://api.your-domain.example` (no `/api` suffix). This is a public routing
address, not a token. The build refuses missing/local/insecure origins instead of publishing a broken
frontend pointed at localhost.

The [build script](frontend/scripts/vercel-build.mjs) builds Vite assets, copies them to the static
output, and writes edge routing for:

1. `/api` and `/api/*` -> the external FastAPI backend, with private/no-store responses.
2. Fingerprinted assets -> immutable static caching.
3. Application deep links -> the React entry page.

API traffic is rewritten at the edge, not relayed through a Node Function. Cookies stay first-party;
existing relative `/api` calls do not need to be rewritten throughout the application. Preview
hostnames require their own allowed backend origin; production settings do not silently allow every
`*.vercel.app` deployment. A new backend origin requires rebuilding the frontend.

## Commands after browser sign-in

Run from this repository root:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh auth refresh --hostname github.com --scopes workflow
git push -u origin main
```

If the repository already exists, inspect its history before setting the remote and pushing. Never
force-push over existing work. For Vercel:

```sh
cd frontend
npx vercel login
npx vercel link
npx vercel env add FORMIQO_API_ORIGIN production
npx vercel --prod
```

After linking, configure the project root directory to `frontend` relative to the repository. Enable
GitHub integration in Vercel for automatic deployments on future pushes.

## Verification before calling it live

- GitHub push returns a repository URL and the remote main commit matches the local commit.
- Vercel returns a Ready production deployment and its actual URL.
- Frontend deep links, `/api/health` and `/api/config` work through that URL.
- Use synthetic documents to test cookie persistence, ATS scoring, job matching, records export,
  upload/conversion/polling/download, and PDF/DOCX export across a page refresh.
- The backend has persistent PostgreSQL/volume storage and survives a restart without losing records.
- No `.env`, local databases, private uploads, `.vercel` auth files or test artifacts are in Git.

Local preparation checks: `npm test`, `npm run test:deployment` (four routing/validation checks),
`npm run build`. A build with an example backend origin validates the output structure only; it is
**not evidence that a backend was hosted or a live deployment works**.
