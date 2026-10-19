# Razorpay Subscriptions — setup & operations

Recurring subscription billing built on the Razorpay **Subscriptions** API (mandate-based auto-debit), wired into the existing plan/feature system.

- **Backend:** `invoice_api/billing/`
- **Frontend:** `bill_makeing_sof/src/pages/Billing.jsx` → route `/billing`
- **Tests:** `python manage.py test billing` — 39 tests, all offline (the Razorpay client is mocked)

---

## How it fits the existing system

`CompanySubscription` (companies app) stays the **single source of truth for entitlement** — what a tenant may use. Nothing in the feature gates changed; `middleware.get_enabled_features` reads the same rows it always did.

The billing app owns the **money** side and writes entitlement as a side effect:

```
Razorpay  ──webhook──▶  billing.webhooks  ──▶  billing.services.apply_entitlement
                                                        │
                                                        ▼
                                            companies.CompanySubscription
                                                        │
                                                        ▼
                                    middleware → request.features → HasFeature gates
```

### Three rules the code enforces

1. **Entitlement is granted by webhooks, never by the browser.** The Checkout callback is signature-verified and used only to trigger an immediate re-sync so the page updates without waiting. It cannot itself unlock a plan.
2. **Amounts always come from the database.** The client sends a `plan_code` and a `period`; the price is looked up server-side. There is a test asserting that an `amount` in the request body is ignored.
3. **Every entitlement write takes a row lock** (`select_for_update`) so two webhooks arriving together cannot interleave and violate the one-active-subscription-per-company constraint.

---

## Setup

### 1. Install the dependency

```bash
pip install razorpay==1.4.2     # already added to requirements.txt
```

### 2. Enable Subscriptions on your Razorpay account — **currently blocking**

Dashboard → **Subscriptions**. It is a separate product from Payments and is **off by default**. On test accounts Razorpay support often has to switch it on; it is not always self-serve.

**How this failure looks** (confirmed on the `rzp_test_TKYQ2afloTOVR0` account):

```
GET /payments  →  HTTP 200      ← credentials are valid
GET /plans     →  HTTP 401 {"error": "Unauthorized"}
```

Two details worth knowing, because both are misleading:

- The **same key** authenticates against `/payments` and is refused on `/plans`. A 401 here is the product gate, not a bad key. Do not go re-check your credentials.
- The body is a bare `{"error": "Unauthorized"}` string, not Razorpay's usual `{"error": {"code": …, "description": …}}` envelope. Code that assumes the envelope will crash on it.

`manage.py verify_razorpay` performs exactly this differential — `/payments` first, then `/plans` — and names the cause when they disagree.

### 3. Environment variables

`invoice_api/.env` already has the test keys under the legacy names `key_id` / `key_secret`, which settings reads as a fallback. The one thing you must add:

```dotenv
RAZORPAY_WEBHOOK_SECRET=<the secret you set in the dashboard>
```

Until this is set the webhook endpoint returns **503** rather than accepting unverified state changes. That is deliberate — a billing webhook with no signature check is a "give me a free Enterprise plan" endpoint.

### 4. Migrate

```bash
python manage.py migrate billing
```

`0002` backfills the new `subscription.manage` permission onto every existing **Company Admin** role. Without it no tenant admin can reach the billing endpoints.

### 5. Check the connection

```bash
python manage.py verify_razorpay --probe-subscriptions
```

Checks credentials, authentication, that Subscriptions is enabled, and that webhook signature verification works.

### 6. Push your plans to Razorpay — **required before anyone can subscribe**

```bash
python manage.py sync_razorpay_plans --dry-run   # see what would be pushed
python manage.py sync_razorpay_plans
```

Creates a Razorpay Plan for every priced plan × period. Free plans are skipped — the Free tier never touches Razorpay.

This is not optional. The checkout path deliberately **cannot** create plans (`allow_create=False`): Razorpay rate-limits plan creation, so provisioning them during checkout means one impatient customer clicking Subscribe twice can trip the limit for everyone and leave orphan plans behind. If you skip this step, `/api/billing/subscribe/` returns a 503 telling you to run it.

The command is safe to re-run. Before creating anything it lists the plans already on your Razorpay account and **adopts** any that match on `notes.plan_code`, `notes.period`, period and amount — so orphans from an earlier failed run get reused instead of duplicated.

### 7. Register the webhook

Dashboard → Settings → Webhooks → Add New Webhook.

**URL:** `https://api.yashadvertisinggroup.com/api/billing/webhook/razorpay/`

**Events:** `subscription.authenticated`, `subscription.activated`, `subscription.charged`, `subscription.updated`, `subscription.pending`, `subscription.halted`, `subscription.paused`, `subscription.resumed`, `subscription.cancelled`, `subscription.completed`, `payment.failed`

Paste the same secret you put in `.env`.

For local testing, expose your dev server (`ngrok http 8000`) and register the ngrok URL.

### 8. Schedule the downgrade job

```cron
0 2 * * * cd /path/to/invoice_api && python manage.py expire_subscriptions        >> logs/expire.log 2>&1
5 2 * * * cd /path/to/invoice_api && python manage.py apply_scheduled_plan_changes >> logs/billing.log 2>&1
```

The second one applies downgrades whose effective date has arrived. It is idempotent.

> `expire_subscriptions` was already documented as required in `SUBSCRIPTION_SYSTEM.md` but is scheduled nowhere in the repo (BUGS.md H41). Both lines belong in the same crontab.

---

## Plan change behaviour

| Change | When it applies | Re-authorisation? | Mechanism |
|---|---|---|---|
| Free → paid | On payment | Yes — first mandate | new Razorpay subscription |
| Upgrade, same period | Immediately | No | `subscription.edit(schedule_change_at='now')` |
| Downgrade, same period | End of current period | No | `subscription.edit(schedule_change_at='cycle_end')` + local `ScheduledPlanChange` |
| Any change of period (monthly ↔ yearly) | Upgrade now / downgrade at period end | **Yes** | Razorpay cannot move a mandate between periods, so the old subscription is cancelled and a new one created |
| Paid → Free | End of current period | n/a | cancel at cycle end |

Downgrades never refund and never shorten access you have already paid for. The API returns `requires_checkout: true` when the user must go through Checkout again; the UI handles both paths.

---

## API

### Tenant — `subscription.view` to read, `subscription.manage` to write

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/billing/plans/` | Plans, prices, features, which is current |
| GET | `/api/billing/subscription/` | Entitlement + mandate + any scheduled change |
| GET | `/api/billing/preview/?plan_code=&period=` | Direction, days left, unused credit |
| POST | `/api/billing/subscribe/` | `{plan_code, period}` → Checkout payload |
| POST | `/api/billing/verify/` | Checkout callback; verifies signature, re-syncs |
| POST | `/api/billing/change-plan/` | `{plan_code, period}` |
| POST | `/api/billing/cancel/` | `{at_cycle_end}` |
| GET | `/api/billing/payments/` | This company's payments only |

Every one of these resolves the company from `request.company`. **No endpoint accepts a company id.**

### Product Owner — `IsProductOwner`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/billing/health/` | Config check, stale plans, failed webhooks |
| POST | `/api/admin/billing/sync-plans/` | Push plans to Razorpay |
| GET | `/api/admin/billing/razorpay-plans/` | Plan mappings + staleness |
| GET | `/api/admin/billing/subscriptions/` | All mandates (`?status=`, `?company_id=`) |
| POST | `/api/admin/billing/subscriptions/<id>/reconcile/` | Re-fetch from Razorpay and re-apply |
| GET | `/api/admin/billing/payments/` | All payments |
| GET | `/api/admin/billing/webhook-events/` | Delivery log (`?status=failed`) |
| GET | `/api/admin/billing/scheduled-changes/` | Queued downgrades |
| POST | `/api/admin/billing/apply-scheduled/` | Run the downgrade job now |

### Webhook — unauthenticated, signature is the authentication

`POST /api/billing/webhook/razorpay/`

---

## Status mapping

| Razorpay | `CompanySubscription` | Effect |
|---|---|---|
| `created`, `authenticated` | *unchanged* | Mandate approved but not charged — grants nothing |
| `active` | `active` | Plan granted, `end_date` = `current_end` |
| `pending`, `halted` | `past_due` | Charge failed; existing 7-day grace applies |
| `cancelled`, `completed`, `expired` | reverts to Free | Or applies a due `ScheduledPlanChange` |

---

## Testing with Razorpay test cards

Test mode banner appears automatically when the key starts `rzp_test_`.

- **Card:** `4111 1111 1111 1111`, any future expiry, any CVV
- **UPI:** `success@razorpay`
- **Netbanking:** pick any bank, then "Success"

Razorpay test subscriptions do not auto-charge on a real monthly schedule. To exercise renewal, use the dashboard's **Charge Now** on the subscription, or replay a `subscription.charged` payload at the webhook with a valid signature.

---

## Troubleshooting

Razorpay SDK errors never reach the user as a 500. Every call goes through `razorpay_call()`, which translates them into a `BillingUnavailable` carrying a readable message, the right HTTP status, and a `retryable` flag the UI uses to offer a Try again button.

| Symptom | Status | Cause & fix |
|---|---|---|
| "Razorpay is rate-limiting this account" | 429 | Too many API calls, usually repeated plan creation. Wait a minute, then run `sync_razorpay_plans` so plans exist ahead of time. Retryable — nothing was charged. |
| "The Subscriptions product is not enabled" | 503 | Enable it at Dashboard → Subscriptions. Razorpay reports this as `The requested URL was not found on the server`, which is why it is translated. |
| "Razorpay returned 401 Unauthorized for the Subscriptions API" | 503 | Same cause, different symptom. `/payments` returns 200 while `/plans` returns 401 — the keys are fine, the product is not activated. See step 2. |
| "…has not been set up in Razorpay yet" | 503 | Run `sync_razorpay_plans`. Expected on a fresh install. |
| "Could not reach Razorpay" | 502 | Network, DNS or proxy. Retryable. |
| Webhook returns 503 | 503 | `RAZORPAY_WEBHOOK_SECRET` is unset. |
| Webhook returns 400 | 400 | Signature mismatch — wrong secret, or a proxy is re-serialising the body. The signature is computed over the raw bytes. |

A failed `subscribe` leaves no half-built state: no `BillingSubscription` row, no entitlement change. There is a test asserting this.

### When the error message doesn't make sense

```bash
python manage.py razorpay_debug                 # read-only
python manage.py razorpay_debug --create-plan   # also attempts one ₹1 plan
```

This bypasses the SDK and the app's error handling entirely, hitting `api.razorpay.com` with `requests` and printing the raw HTTP status plus Razorpay's `code` / `description` / `reason` / `source` / `step`. It checks auth against `/payments` first, then `/plans`, so it separates "credentials are wrong" from "Subscriptions is not activated".

**Do not trust the SDK's exception class.** `razorpay.Client.request` ends with:

```python
elif str.upper(code) == ERROR_CODE.SERVER_ERROR:
    raise ServerError(msg)
else:
    raise ServerError(msg)     # ← catch-all for every unrecognised code
```

So `ServerError` is the default bucket, not evidence that Razorpay is down. An unactivated feature or a bad key surfaces as `ServerError` too. Only the `description` is meaningful, which is why `razorpay_call()` always includes it verbatim and logs it at ERROR under the `billing` logger.

## Operational notes

**A missed webhook is recoverable.** Every delivery is stored in `WebhookEvent`, keyed on Razorpay's `X-Razorpay-Event-Id` with a unique constraint. Replays are no-ops. If one failed, find it under `?status=failed` and hit `reconcile` on the subscription — that re-fetches authoritative state from Razorpay and re-applies it.

**Price changes create new Razorpay plans.** Razorpay plans are immutable. When you change a price, `ensure_razorpay_plan` deactivates the old mapping and creates a new plan. Companies already on a mandate keep their old price until they change plan — which is the correct behaviour, but it means a price rise does not apply retroactively. `/api/admin/billing/health/` lists stale mappings.

**`LocMemCache` will bite you here.** `settings.py` configures no `CACHES`, so the per-process fallback is used. When a webhook grants a plan, `signals.on_subscription_change` clears `company_sub:{id}` — but only in the worker that handled the webhook. Other workers serve a stale subscription for up to an hour. A customer can pay and still see the old plan depending on which worker answers. **Configure Redis before this goes live** (BUGS.md H11).

**Timezone fix included.** `CompanySubscription.is_working()`, `middleware.get_active_subscription` and `expire_subscriptions` used `timezone.now().date()`, which yields the *UTC* date under `TIME_ZONE='Asia/Kolkata'`. Between 00:00 and 05:30 IST a subscription starting today read as not-yet-started — a customer who paid in that window would have been charged and locked out. All three now use `timezone.localdate()`. This was BUGS.md H17; it sits directly in the payment path, so it is fixed here rather than deferred.

---

## Files

```
invoice_api/billing/
├── models.py                      RazorpayPlan, BillingSubscription,
│                                  ScheduledPlanChange, PaymentRecord, WebhookEvent
├── razorpay_client.py             client factory + signature verification
├── services.py                    plan sync, lifecycle, entitlement state machine
├── webhooks.py                    signature-verified, idempotent receiver
├── admin.py                       Django admin registration
├── tests.py                       39 tests (Razorpay mocked)
├── api/{serializers,views,views_admin,urls}.py
├── migrations/0001_initial.py
├── migrations/0002_seed_subscription_manage_permission.py
└── management/commands/
    ├── verify_razorpay.py             live connectivity check
    ├── sync_razorpay_plans.py         push plans to Razorpay
    └── apply_scheduled_plan_changes.py  daily downgrade job
```

Touched outside the app: `settings.py` (Razorpay config, `INSTALLED_APPS`, `billing` logger), `invoice_api/urls.py`, `accounts/authz_seed.py`, `companies/models.py` + `middleware.py` + `expire_subscriptions.py` (timezone fix), `requirements.txt`, `.env`, and on the frontend `App.jsx`, `comonant/navbar.jsx`, `pages/Billing.jsx`.

---

## Before going live

1. Set `RAZORPAY_WEBHOOK_SECRET` — webhooks are rejected without it.
2. Configure Redis `CACHES` — otherwise paid upgrades appear inconsistently across workers.
3. Swap the test keys for live keys, and **rotate the test secret** that has been shared in chat and sits in git-tracked reach.
4. Add both cron entries.
5. Run `verify_razorpay --probe-subscriptions` against the live account.
6. Confirm `/api/admin/billing/health/` is all green.
