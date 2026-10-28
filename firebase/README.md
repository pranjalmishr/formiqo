# Firebase backend and database status

User requirement: host Formiqo's backend and database in the provided Firebase project,
keeping the Vercel frontend and preserving working resume, ATS, job-match and conversion
workflows. No existing project data or security rules have been replaced.

## Verified project

- Firebase project: **nitre-d8cdd** (display name **Nitre**), project number **721926516617**.
- Project association is saved in [../.firebaserc](../.firebaserc).
- Firebase CLI browser authentication succeeded and the project is accessible.
- The default **Firestore Native** database exists in **nam5**.
- Authenticated administrative create/read/delete was tested with one synthetic document
  under `formiqo_deployment_checks`. The document was deleted in the test's cleanup step.
  This proves IAM connectivity, not browser security-rule correctness or application migration.
- The supplied browser SDK configuration is not a backend service-account credential.
  Its API key was not copied into Python code, secret files, or Git.

## Deployment blockers (observed, not inferred)

| Requirement | Result |
| --- | --- |
| Google Cloud billing | `billingEnabled: false`; no billing account attached |
| Cloud Run service | API disabled/unavailable (403); no Formiqo backend deployed |
| Supplied bucket `nitre-d8cdd.firebasestorage.app` | Storage API returned 404: bucket does not exist |
| Cloud SQL | No instances listed |
| Current Formiqo database | Existing SQLAlchemy SQLite/PostgreSQL implementation; not migrated to Firestore |

Enable the **Blaze** billing plan in the [Firebase console](https://console.firebase.google.com/project/nitre-d8cdd/overview)
before provisioning the backend and durable file storage. Blaze is pay-as-you-go; upgrading is not
a promise of zero charges. No billing account was linked and no billable resources were created
by this work.

## Compatibility constraints and next implementation steps

1. **Database path:** Firestore is not a drop-in PostgreSQL/SQLAlchemy driver. Replacing it
   requires migrating model access, joins, session ownership, optimistic revisions and
   transactions across the backend, plus data migration and regression tests. The supplied
   web configuration alone does not do that. Firebase SQL Connect/Cloud SQL PostgreSQL is
   the lower-change alternative if preserving the relational database is preferred; it is
   not provisioned or configured here.
2. **Python backend:** package the existing native tools in Cloud Run under this project.
   Do not publish a Vercel Function and call it equivalent to the current worker service.
3. **Files:** provision private Cloud Storage; durable originals, prepared inputs and
   converted outputs must not depend on Cloud Run's temporary filesystem. Preserve
   ownership checks on downloads and retention cleanup.
4. **Background work:** implement durable task execution and idempotent result commits,
   or retain an explicitly single-instance execution model with continuously allocated CPU
   and disclosed interruption handling. Do not silently rely on post-response tasks on a
   request-throttled instance.
5. **Authentication:** keep current guest/account ownership during migration. Do not turn
   on public Firestore access rules to make a browser demo work. Runtime server credentials
   should use a least-privilege attached service account, not a committed private key.
6. **Deployment:** after a real Cloud Run origin passes upload/scoring/conversion/records
   checks, set Vercel `FORMIQO_API_ORIGIN` and deploy the frontend. There is no live backend
   origin or production Vercel deployment yet.

## Official references

- [Cloud Run and Cloud SQL PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/connect-instance-cloud-run)
- [Firebase SQL Connect](https://firebase.google.com/docs/sql-connect)
- [Using existing SQL Connect databases](https://firebase.google.com/docs/sql-connect/manage-services-and-databases)
- [Cloud Storage / Google Cloud integration](https://firebase.google.com/docs/storage/gcp-integration)

## Current scope

Project association and live administrative Firestore connectivity are complete. Backend
hosting, storage provisioning and database migration are **not complete**. The existing local
application is unchanged; no saved resumes or score records were uploaded to this project.
