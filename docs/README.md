# Architecture docs

How the main features work end to end, across the Django API (`invoice_api/`), the web app (`bill_makeing_sof/`) and the mobile app (`MobileApp/`).

| Doc | Covers |
|---|---|
| [architecture.md](architecture.md) | System overview: the three apps, auth, tenancy, permissions and plan gates |
| [invoice-generation.md](invoice-generation.md) | Creating and editing an invoice: numbering, header defaults, line items, totals |
| [pdf-export.md](pdf-export.md) | Turning invoices into PDFs: templates, the HTML (WeasyPrint) and YAML (ReportLab) renderers, bulk export |
| [user-signup.md](user-signup.md) | Email, Google and phone signup, company setup, starter data, trial |
| [whatsapp-messaging.md](whatsapp-messaging.md) | Sending an invoice on WhatsApp: own vs shared number, limits, Meta API calls |
| [inventory.md](inventory.md) | Products, categories, stock movements, and how invoices deduct stock |
| [theming.md](theming.md) | Light/dark theme in the mobile app, design tokens in the web app, why PDFs stay white |

Related docs elsewhere in the repo (not duplicated here): `BILLING.md`, `SUBSCRIPTION_SYSTEM.md`, `FEATURES.md`, `DEPLOYMENT.md`, `MobileApp/DARK_THEME.md`, `bill_makeing_sof/DESIGN_SYSTEM.md`.

## Keeping these docs current

These docs describe the code as it is. **Any change to one of the features above must update its doc in the same change.** The table below says which code belongs to which doc; if you touch a file listed there, re-read the doc and fix whatever is now wrong (steps, endpoints, file paths, gates, known gaps).

| If you change… | Update |
|---|---|
| `invoice_api/invoice/api/views.py` (InvoiceView, Invoice_update, line-item views), `invoice/line_calc.py`, `invoice/numbering.py`, `invoice/header_config.py`, `invoice/serializers.py`, `MobileApp/services/invoices.ts`, `MobileApp/components/invoice-form.tsx`, `MobileApp/lib/invoice-calc.ts`, `bill_makeing_sof/src/comonant/new_bill_body.jsx`, e-way bills: `invoice/eway.py`, `invoice/api/views_eway.py`, `MobileApp/services/eway.ts`, `MobileApp/app/invoice/eway/[id].tsx`, web `comonant/Bill/EwayBillPanel.jsx`, `pages/EwayBills.jsx` | invoice-generation.md |
| `invoice_api/invoice/export.py`, `PdfMaker` / `BulkExport` views, `yaml_reader.py`, `submit.py`, `pdf_fonts.py`, `upi_qr.py`, `invoice_api/gst.py`, `yaml_manager/` | pdf-export.md |
| `invoice_api/accounts/api/views.py` (Register/Login/Google), `views_phone.py`, `views_onboarding.py`, `accounts/serializers/serializers.py`, `accounts/signals.py`, `companies/trial.py`, `MobileApp/app/(auth)/*`, `MobileApp/app/company-setup.tsx`, `MobileApp/store/session.ts`, `bill_makeing_sof/src/pages/signup.jsx`, `CompanyForm.jsx` | user-signup.md |
| `invoice_api/bill_share/`, `invoice_api/whatsapp_integration/`, `MobileApp/services/whatsapp.ts`, `MobileApp/app/whatsapp.tsx`, web `WhatsApp*.jsx`, `ExportDropdown.jsx` | whatsapp-messaging.md |
| `invoice_api/inventory/`, `MobileApp/services/inventory.ts`, `MobileApp/app/inventory/*`, `inventory-picker.tsx`, `line-item-modal.tsx`, web `inventory.jsx` / `comonant/inventory/` | inventory.md |
| `MobileApp/constants/theme.ts`, `hooks/use-theme.ts`, `store/prefs.ts`, `theme-mode-picker.tsx`, `app/_layout.tsx` (theme parts), `bill_makeing_sof/src/style/tokens.css`, `src/index.css` | theming.md |
| Auth classes, middleware, `invoice_api/permissions.py`, `scoping.py`, `limits.py`, root `urls.py` | architecture.md |

When a flow gains a new step, endpoint or gate, add it. When a "Known gaps" item is fixed, remove it.

_Last reviewed against the code: 2026-11-17._
