# Formiqo product upgrade

## Existing implementation inspected
- React 18 / Vite / TypeScript / Tailwind; Router, RHF/Zod, TipTap, Radix components, Recharts.
- FastAPI / SQLAlchemy; existing guest/account ownership, versions, expiry, jobs and protected downloads.
- Five template configurations currently vary typography/spacing but share one-column export structure.
- Current editor edits one section separately from the resume; builder is a ten-step form.
- PDF/DOCX extraction exists, but originals are removed after processing. Recreation needs explicit retained-source storage.
- Conversion jobs work, but discovery/configuration/preview and PDF/image manipulation need dedicated workflows.

## Implementation sequence
1. Shared template definitions, 18 real structures, gallery/filter/favorites, paginated HTML canvas, style controls and matching export path.
2. Retained-source import review, layout observations, uncertain fields and editable reconstruction.
3. Capability-driven tool discovery, previews and tested PDF/image operations; richer ATS evidence/review UX.
4. Regression, accessibility, fidelity and security checks; update supported/pending release gates.

The existing app remains the project of record. Existing saved content and guest/account ownership must remain compatible.
Sample gallery data must be labeled and never inserted into a user's resume automatically.
