# invoice_api

Monorepo: Django API (`invoice_api/`), web app (`bill_makeing_sof/`), Expo mobile app (`MobileApp/`).

## Architecture docs — keep them in sync

`docs/` describes how the main features work end to end. Read the relevant doc before changing one of these features:

- `docs/architecture.md` — apps, auth, tenancy, permission and plan gates
- `docs/invoice-generation.md` — creating/editing invoices, numbering, line items, totals
- `docs/pdf-export.md` — PDF export, templates, WeasyPrint/ReportLab renderers, bulk export
- `docs/user-signup.md` — email/Google/phone signup, company setup, trial
- `docs/whatsapp-messaging.md` — sending invoices on WhatsApp
- `docs/inventory.md` — inventory products, stock movements, stock deduction from invoices
- `docs/theming.md` — mobile light/dark theme, web design tokens

**Rule: any change to one of these features must update its doc in the same change** — new or removed steps, endpoints, gates, file paths, and the "Known gaps" list (remove a gap when you fix it). The file-to-doc map is in `docs/README.md`. Before finishing, check whether the files you touched appear in that map, and if so, update the doc and its "Last reviewed" date. Do this without being asked.
