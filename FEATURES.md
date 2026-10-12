# Feature Catalog & Plan Tiering

Two parts:

- **Part 1 — As-built.** What the code actually defines and enforces today.
- **Part 2 — Proposed packaging.** A complete Free / Pro / Enterprise model covering *every* capability in the product, including the ones that aren't gated yet.

Feature/plan models live in `invoice_api/companies/models.py`. The only authoritative plan matrix in the repo is the seed data in `companies/migrations/0007_migrate_legacy_subscriptions.py` and `0008_whatsapp_shared_number_feature.py`.

---

# Part 1 — As-built

## 1.1 Feature codes that exist

| Code | Name | Seeded in |
|---|---|---|
| `invoicing` | Invoicing | `0007` |
| `inventory` | Inventory | `0007` |
| `whatsapp_integration` | WhatsApp Integration (own WABA) | `0007` |
| `advanced_reports` | Advanced Reports | `0007` |
| `template_designer` | Template Designer | `0007` |
| `api_access` | API Access | `0007` |
| `whatsapp_shared_number` | Shared WhatsApp Number | `0008` |

Limit keys in use: `invoices_per_month`, `users`, `sends_per_day`. An empty `limits` JSON (`{}`) means **unlimited** — `enforce_limit` treats a missing key as `None` (`invoice_api/limits.py:43`).

## 1.2 Plan matrix — seed migrations (the intended state)

| | **Free** — ₹0 | **Pro** — ₹499/mo, ₹4,999/yr | **Enterprise** — ₹1,999/mo, ₹19,999/yr |
|---|---|---|---|
| `invoicing` | 50 invoices/mo, 2 users | 1,000 invoices/mo, 10 users | unlimited |
| `inventory` | ✅ | ✅ | ✅ |
| `whatsapp_shared_number` | 5 sends/day | 50 sends/day | platform default |
| `whatsapp_integration` | — | ✅ | ✅ |
| `template_designer` | — | ✅ | ✅ |
| `advanced_reports` | — | ✅ | ✅ |
| `api_access` | — | — | ✅ |

## 1.3 Plan matrix — live `db.sqlite3` (has drifted)

Plans are runtime-editable by the Product Owner (`companies/api/views_admin.py`, UI at `PlatformAdmin.jsx`), so the DB no longer matches the seed:

| | Free | Pro | Enterprise |
|---|---|---|---|
| `invoicing` | **`{}` — uncapped** ⚠️ | 1,000/mo, 10 users | unlimited |
| `inventory` | **removed** ⚠️ | ✅ | ✅ |
| `whatsapp_shared_number` | **10/day** (was 5) | 50/day | platform default |
| `whatsapp_integration` | — | ✅ | ✅ |
| `template_designer` | — | ✅ | ✅ |
| `advanced_reports` | — | ✅ | ✅ |
| `api_access` | — | — | ✅ |

**Two bugs to fix:**

1. ⚠️ **Free tier is currently uncapped on invoices and seats.** `free → invoicing` has `limits = {}`, so `enforce_limit` never trips. This is the single most costly issue in the table — free accounts can create unlimited invoices and invite unlimited users.
2. ⚠️ **Feature row `id=8` has `name` and `code` swapped** — `name='purchases_invoice'`, `code='Purchases Invoice'`. Created 2026-08-01, presumably via the Platform Admin UI. Attached to no plan, referenced by no code. Delete it or fix the field order.

## 1.4 Where gates are actually enforced

| Gate | Location |
|---|---|
| `advanced_reports` | `invoice/api/views.py:388` — bulk export only |
| `inventory` | `inventory/api/views.py:12` — all viewsets |
| `whatsapp_integration` | `whatsapp_integration/api/views.py:11` — config, templates, send-test, oauth |
| `whatsapp_shared_number` | `bill_share/views.py` + `whatsapp_integration/resolver.py` — 24h rolling send count |
| `template_designer` | `yaml_manager/api/views.py` — POST only (reads stay open for PDF rendering) |
| limit `invoicing.invoices_per_month` | `invoice/api/views.py:86` |
| limit `invoicing.users` | `accounts/api/views_invites.py:118` |
| `api_access` | **nowhere** — dead feature |

Blocked requests return `403` with `code: "upgrade_required"`; `bill_makeing_sof/src/axios.js:65` turns that into an amber upgrade toast.

## 1.5 Enforcement gaps

Re-checked against the code and pinned by tests in `invoice/tests_report_gates.py` (the earlier version of this table was stale):

| Gap | Status |
|---|---|
| Reports gated only in UI | **Closed.** `sales-report`, `cash-flow`, `gst-summary` and `ledger/…` enforce `advanced_reports` (plan) *and* `report.view` (permission) server-side. |
| `/api/pdf/` is `AllowAny` | **Closed.** Requires authentication and is company-scoped. |
| Inventory skips permissions | **Closed.** All inventory viewsets require the `inventory` feature and `inventory.manage`. |
| Purchase/OCR endpoints open | **Closed.** `upload`, `status`, `pending-jobs`, `ocr-jobs` and `purchase-summary` require `purchases_invoice` plus `invoice.view`/`invoice.create`; uploads are quota-limited. |
| `bulk_export` had no permission check | **Closed.** Now also requires `invoice.view` (it exports the same data as the invoice list). |
| `api_access` unenforced | Open. Enterprise-only in seed and DB, but the `ServiceToken` auth path (`accounts/authenticate.py`) never checks it. |
| Navbar fails open | Open (web only). `navbar.jsx:40` — `hasFeature` returns `true` while access state is loading. |
| Customer/vendor/product edit & delete not company-scoped | Open. `companies/api/views.py` and the line-item `product/` endpoints look records up by id alone, so a user who guesses another company's id can edit or delete it. |

---

# Part 2 — Proposed packaging

Everything the product does, tiered — including capabilities that have no feature code yet. **Bold** rows are new gates that would need to be built.

## 2.1 Recommended matrix

### Core invoicing

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| Create / edit / delete invoices | 25/mo | 1,000/mo | Unlimited | `invoicing.invoices_per_month` |
| Team seats | 2 | 10 | Unlimited | `invoicing.users` |
| Customers & vendors | ✅ | ✅ | ✅ | ungated |
| Product catalog | ✅ | ✅ | ✅ | ungated |
| PDF generation & download | ✅ | ✅ | ✅ | ungated *(but close `AllowAny`)* |
| **Payments & credit/debit notes** | — | ✅ | ✅ | **`payments`** (new) |
| **Custom invoice fields** | — | ✅ | ✅ | **`custom_fields`** (new) |
| **Data retention** | **12 months** | Unlimited | Unlimited | **`invoicing.retention_months`** (new) |

I'd drop Free from 50 → 25 invoices/month. 50/mo is a real small business, not a trial — that's the tier most likely to never convert.

### Templates

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| Use published gallery templates | ✅ | ✅ | ✅ | ungated |
| Design / clone / upload custom templates | — | ✅ | ✅ | `template_designer` |
| **Saved custom templates** | 0 | **10** | Unlimited | **`template_designer.max_templates`** (new) |
| **Remove product branding from PDFs** | — | ✅ | ✅ | **`white_label`** (new) |
| **Publish templates to the global gallery** | — | — | ✅ | **`template_publishing`** (new) |

White-label is the classic Free→Pro lever and you already control PDF rendering end-to-end, so it's cheap to add.

### Inventory

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| Categories, suppliers, products | — | ✅ | ✅ | `inventory` |
| Stock movements | — | ✅ | ✅ | `inventory` |
| **Multi-location stock** | — | — | ✅ | **`inventory.locations`** (new) |

The seed grants `inventory` to Free but the live DB doesn't. **Pick one** — I'd keep it Pro-only (matches the DB) and make the seed match, since inventory is a genuine step up from "I just need to send a bill."

### WhatsApp

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| Send via shared number | 5/day | 50/day | 500/day | `whatsapp_shared_number.sends_per_day` |
| Connect own WABA | — | ✅ | ✅ | `whatsapp_integration` |
| Template sync & management | — | ✅ | ✅ | `whatsapp_integration` |
| **Bulk / scheduled sends** | — | — | ✅ | **`whatsapp_bulk`** (new) |

Revert Free to 5/day (the DB says 10). Give Enterprise an explicit high number rather than `{}` — unlimited outbound WhatsApp is a cost and abuse exposure, not a feature.

### Reports & data

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| Invoice list & basic search | ✅ | ✅ | ✅ | ungated |
| Sales register, cash flow, GST summary, ledgers | — | ✅ | ✅ | `advanced_reports` *(needs backend gate)* |
| Bulk export (Excel) | — | ✅ | ✅ | `advanced_reports` |
| **Scheduled email reports** | — | — | ✅ | **`scheduled_reports`** (new) |

### Purchase / OCR

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| **Purchase invoice OCR extraction** | **3/mo trial** | **50/mo** | **500/mo** | **`ocr_extraction.pages_per_month`** (new) |
| Purchase summary | ✅ | ✅ | ✅ | ungated |
| Vendor management | ✅ | ✅ | ✅ | ungated |

This is the biggest packaging gap. OCR extraction has real per-unit cost and high perceived value, and it's currently free and unmetered for everyone. Metering it is the highest-ROI change in this document. The `Purchases Invoice` row someone half-created in the DB suggests this was already the intent.

### Access control & admin

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| Company Admin / Member roles | ✅ | ✅ | ✅ | ungated |
| **Custom roles & groups** | — | ✅ | ✅ | **`advanced_authz`** (new) |
| **Per-user grant/deny overrides** | — | — | ✅ | **`advanced_authz`** (new) |
| Email invites | ✅ (to seat cap) | ✅ | ✅ | `invoicing.users` |
| **Company audit log** | — | 30 days | Unlimited | **`audit_log.retention_days`** (new) |
| **Multiple companies per account** | 1 | 3 | Unlimited | **`multi_company.max_companies`** (new) |
| Google / social login | ✅ | ✅ | ✅ | ungated |

`multi_company` is worth real money to accountants and agencies, who are exactly the users who'd otherwise sit on Free forever.

### Platform / integration

| Capability | Free | Pro | Enterprise | Code |
|---|---|---|---|---|
| Service-token API access | — | — | ✅ | `api_access` *(exists, unenforced)* |
| **Webhooks** | — | — | ✅ | **`webhooks`** (new) |
| **SSO / SAML** | — | — | ✅ | **`sso`** (new) |
| **Priority support & SLA** | — | — | ✅ | contractual, not a gate |

## 2.2 Proposed pricing

| | Free | Pro | Enterprise |
|---|---|---|---|
| Monthly | ₹0 | ₹499 | ₹2,999 |
| Yearly | ₹0 | ₹4,999 *(2 months free)* | ₹29,999 |

Pro at ₹499 is well positioned — leave it. Enterprise at ₹1,999 is only 4× Free-to-Pro for unlimited seats, unlimited invoices, API access and SSO; that's underpriced for the segment. ₹2,999 is still comfortably below what comparable Indian GST invoicing tools charge for an unlimited-seat tier, and you can discount into deals rather than starting from a low anchor.

Consider a **Starter** tier at ₹199 (200 invoices/mo, 5 users, shared WhatsApp, no inventory) if Free→Pro conversion turns out weak — ₹0 → ₹499 is a wide gap for a solo trader.

## 2.3 Suggested implementation order

1. **Restore Free's `invoicing` limits in the DB** — one row. Stops unmetered free usage today.
2. **Gate the reports endpoints server-side** — `advanced_reports` on the four report views. Closes the bypass.
3. **Fix or delete feature row `id=8`.**
4. **Meter OCR extraction** (`ocr_extraction.pages_per_month`) — highest revenue impact of the new gates.
5. **Enforce `api_access`** on the service-token auth path — the feature is already sold to Enterprise.
6. **Add `white_label` and `multi_company`** — strongest Free→Pro conversion levers.
7. Reconcile the seed migration with the intended matrix so fresh installs and the live DB agree.
8. Fix `navbar.jsx:40` to fail *closed* while access state loads.

---

*Generated from the codebase on 2026-08-01. Part 1 verified against `companies/migrations/0007`, `0008`, live `db.sqlite3`, and the `HasFeature` / `enforce_limit` call sites. Part 2 is a recommendation, not current behavior.*
