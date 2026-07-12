# Subscription & Authorization System

Multi-tenant, subscription-gated authorization for the invoice API.
Backend branch: `feature/subscription-authz` · Frontend branch (bill_makeing_sof): `feature/subscription-authz-ui`

## Concepts

- **SubscriptionPlan** (`free`, `pro`, `enterprise`, …) → has **Features** via **PlanFeature** (with optional JSON `limits`, e.g. `{"users": 5, "invoices_per_month": 100}`).
- A company gets exactly one working **CompanySubscription** (`active` or `trialing`; `past_due` keeps working for a 7-day grace period).
- **Roles / Groups / Direct permissions** control what each user can do inside their company. Direct *deny* always wins. System roles (`Company Admin`, `Member`) and the global `Product Owner` role are seeded.
- Every request resolves `request.company / features / permissions` lazily (after JWT auth), with membership validation — `X-Company-ID` spoofing returns 403.

## Feature gates currently applied

| Endpoint | Required feature |
|---|---|
| `/api/whatsapp/*`, `/api/share_by_whatsapp/` | `whatsapp_integration` |
| `/api/inventory/*` | `inventory` |
| Bulk export (`/api/bulk_export/`-style) | `advanced_reports` |
| Invoice create | limit `invoicing.invoices_per_month` (per company, per month) |
| User invite | limit `invoicing.users` (members + pending invites) |

Blocked requests return **403 with code `upgrade_required`** so the frontend can show an upgrade prompt. The navbar hides Inventory / Reports / WhatsApp entries when the plan lacks the feature.

## Management

- **Product Owner** (`is_superuser` or global `Product Owner` role): `/platform-admin` UI or `/api/admin/…` — plan/feature CRUD, per-plan limits, assign/cancel tenant subscriptions, cross-tenant audit log.
- **Tenant Admin** (`role.manage` permission): `/access-control` UI or `/api/authz/…` — roles, groups, per-user grant/deny, email invites, company audit log.

## Required cron job

Natural expiry is enforced at read time (an expired subscription stops working on the next request), but statuses and caches are tidied by a daily job:

```cron
# crontab -e  (adjust paths/venv)
0 2 * * * cd /path/to/invoice_api && python manage.py expire_subscriptions >> logs/expire.log 2>&1
```

## Environment variables

| Var | Purpose |
|---|---|
| `EMAIL_USER` / `EMAIL_PASS` | SMTP credentials for invite mail (Gmail) |
| `FRONTEND_URL` | Base URL used in invite links (default `http://localhost:5173`) |

## Tests

```bash
python manage.py test accounts.tests_authz   # 16 regression tests
```

Covers: spoofing, deny-wins, m2m cache invalidation, trialing subscriptions,
escalation/lockout guards, Product Owner gates, invite flow, feature gates,
invoice limit.
