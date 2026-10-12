# Mobile App — Feature Parity Plan

Goal: bring the Expo app in `MobileApp/` to feature parity with the web app (`bill_makeing_sof`) using the existing Django API (`/api/...`). No new backend product work is needed except the small items in Phase 0.

## 1. Where things stand

**Mobile (`MobileApp/`)** — Expo SDK 54, expo-router 6, React 19 / RN 0.81, axios.
- Done: login + signup screens (UI only), an axios instance (`services/api.ts`), the starter tab layout.
- Not done: token storage, auth guard, every business screen. `(tabs)/index.tsx` and `explore.tsx` are still the Expo template.
- `api.ts` uses `withCredentials` (browser cookies). That does not work reliably in React Native, so auth needs a bearer-token flow.

**Backend** — everything the web app uses is already a REST endpoint under `/api/`:
`login/ register/ google-login/ profile/ user_info/ dashboard/ user-companies/`, `invoice/ product/ product-images/ custom-fields/ invoice-numbering/`, `companies/ vendors/`, `inventory/*`, `sales-report/ cash-flow/ gst-summary/ ledger/ purchase-summary/ purchase/*` (OCR), `yaml/*` (templates), `whatsapp/*`, `billing/*` (Razorpay), `authz/*` (roles, groups, invites, audit log), `share_by_whatsapp/`.
`JWTAuthentication` already accepts an `Authorization: Bearer` header (`accounts/authenticate.py`), so mobile can use it without backend changes.

## 2. Scope decision

Not every web page belongs on a phone. Proposed split:

| Tier | Features |
|---|---|
| **Ship in app** | Auth, dashboard, invoices (create/list/view/share/PDF), customers, vendors, products, inventory, reports (view), purchase OCR (camera upload), WhatsApp send, billing/subscription, profile, team & access (basic), company switcher |
| **Read-only or simplified** | Template gallery (pick default / clone), UI numbering config, audit log, WhatsApp settings |
| **Web-only (link out)** | Invoice template designer / YAML editor, Platform Admin, global-template admin, WeasyPrint preview |

Please confirm or adjust this split. It changes Phase 5–6 scope.

## 3. Architecture (Phase 0 foundation)

1. **Auth** — Store the access/refresh token in `expo-secure-store`, not AsyncStorage. Add an axios request interceptor to attach `Bearer`, and a response interceptor to refresh on 401 and log out on failure.
   - *Verify first:* whether `login/` returns tokens in the JSON body or only sets cookies. If cookie-only, add a small additive change to return `access`/`refresh` for a `X-Client: mobile` header. Check `/api/login_token/` too.
2. **Routing** — Root layout gates on auth state: `(auth)` vs `(app)`. Replace the template tabs with: Home, Invoices, Customers, Inventory, More.
3. **State/data** — `@tanstack/react-query` for fetching, caching and offline-friendly retries. Small `zustand` store (or React context) for session, active company and feature flags.
4. **Entitlements** — On login call `authz/me/` and `billing/subscription/`. Build a `useFeature(code)` and `useCan(permission)` hook plus a `<RequireFeature>` wrapper. Handle the API's `403 { code: "upgrade_required" }` globally with an upgrade sheet (mirrors `axios.js:65` on web).
5. **UI kit** — Shared `Button`, `Input`, `Card`, `ListItem`, `EmptyState`, `Skeleton`, `Toast`, `BottomSheet`, `FormField` (react-hook-form + zod). Move the login screen's hard-coded colours into `constants/theme.ts`.
6. **Config** — `EXPO_PUBLIC_API_URL` per environment (`.env.development`, `.env.production`), EAS build profiles, `app.json` identifiers.
7. **Quality** — Typed API layer in `services/` (one file per domain), ESLint already present, add Jest + React Native Testing Library for hooks and key forms.

## 4. Phases

### Phase 1 — Auth & shell (≈1 wk)
- Login, register, Google login (`expo-auth-session`), logout, forgot-password (if the API supports it).
- Secure token storage, refresh, auth guard, splash gating.
- Company picker (`user-companies/`) and active-company header; invite acceptance via deep link (`/invite/:token`, `expo-linking`).
- Profile screen (`profile/`, `user_info/`) and edit.
- **Exit:** log in on a device, survive app restart, switch company.

### Phase 2 — Invoicing core (≈2–3 wks) — highest value
- Dashboard (`dashboard/`): totals, recent invoices, quick actions.
- Invoice list with search, filters, pull-to-refresh, pagination.
- Create / edit invoice: customer picker, line items from product catalog, tax, discount, numbering (`invoice-numbering/`), custom fields, UPI QR option.
- Invoice detail: view, status, delete, duplicate.
- PDF: fetch `pdf/`, preview with `expo-file-system` + `expo-sharing` / `expo-print`.
- Share: `share_by_whatsapp/`, system share sheet, email.
- Customers (`companies/`) and Vendors (`vendors/`): list, add/edit, detail with outstanding balance.
- Enforce the `invoices_per_month` limit UX (show remaining, upgrade prompt).
- **Exit:** create and share an invoice PDF end-to-end on both platforms.

### Phase 3 — Products & inventory (≈1–2 wks)
- Product catalog (`product/`, properties, images via `expo-image-picker`, crop-ratio setting).
- Inventory (`inventory/products|categories|suppliers|stock-movements`), gated on the `inventory` feature.
- Low-stock indicators; barcode scan to find or add a product (`expo-camera`).
- **Exit:** add stock, see movement history, pick products in the invoice form.

### Phase 4 — Reports & purchases (≈2 wks)
- Sales register, cash flow, GST summary, customer/supplier ledger (read-only tables/charts, date-range filter), gated on `advanced_reports`.
- Export/share: bulk export via `bulk_export/` saved and shared as a file.
- Purchase invoices + vendors; **OCR capture**: camera/gallery → `purchase/upload/` → poll `purchase/status/<job>/` → review/edit extracted fields → save. Show OCR job history (`purchase/ocr-jobs/`).
- **Exit:** photograph a supplier bill and save it as a purchase invoice.

### Phase 5 — Subscription, WhatsApp, team (≈2 wks)
- Billing: plans, current subscription, change/cancel, payment history (`billing/*`). Payment goes through Razorpay Checkout — use the Razorpay RN SDK or open the hosted flow in `expo-web-browser`, then call `billing/verify/`. Entitlement is still granted by webhook (see `BILLING.md`), so the app only triggers a re-sync.
  - Note: Apple/Google may require in-app purchase for digital subscriptions. Decide before store submission (see Risks).
- WhatsApp: mode, config status, template list/sync, send test (`whatsapp/*`).
- Team & access: members, invites (create/resend/revoke), roles/groups list, my permissions, audit log (read-only).
- Templates: gallery browse, preview, clone, set default (`yaml/gallery`, `yaml/<id>/set-default`). Numbering config.

### Phase 6 — Polish & release (≈2 wks)
- Push notifications (`expo-notifications`) for payment/OCR-complete/invite — needs a small backend device-token endpoint.
- Biometric lock (`expo-local-authentication`), dark mode pass, accessibility, tablet layout check.
- Offline: cache lists in React Query persistence; queue invoice drafts locally and sync when online.
- Crash/analytics (Sentry), deep links, app icon/splash, store listings, privacy policy (exists at `/privacy`).
- EAS Build → TestFlight / Play internal testing → staged rollout.
- Note: `mobile_app_bubblewrap/` (a TWA wrapper) is in the repo — decide whether it is retired once the native app ships.

## 5. Backend items to fix alongside (from `FEATURES.md`)

The mobile app will be an extra client of these endpoints, so these gaps matter more once phones hit them:
1. Gate report endpoints server-side with `advanced_reports` (currently UI-only).
2. Close `AllowAny` on `/api/pdf/`.
3. Enforce permissions on inventory and purchase/OCR endpoints.
4. Add mobile token response on login (if needed, see Phase 0).
5. Add a device-token endpoint for push (Phase 6).

## 6. Risks / open questions

- **Store billing rules** — selling Pro/Enterprise through Razorpay inside an iOS app may violate App Store guidelines. Options: sign-up and pay on web only, with the app showing status; or implement IAP. Needs a decision before Phase 5.
- **Cookie vs token auth** — confirm the login response shape (Phase 0).
- **Scope** — template designer and platform admin stay web-only unless you want them.
- **Offline** — full offline invoicing is a big step up in complexity. Plan assumes cached reads + a draft queue only.
- **Testing devices** — iOS simulator is available here; Android needs an emulator or device.

## 7. Suggested order of delivery

`Phase 0 → 1 → 2` gives a usable "create and send an invoice" app (the MVP, ~4–5 weeks). Phases 3–5 can then ship as incremental releases in any order based on what customers ask for; Phase 6 runs in parallel from Phase 2 onward.

## 8. First concrete tasks

1. Check what `login/` returns and decide cookie vs bearer.
2. Add `expo-secure-store`, `@tanstack/react-query`, `zustand`, `react-hook-form`, `zod`, `expo-file-system`, `expo-sharing`, `expo-image-picker`, `expo-camera`.
3. Rebuild `services/api.ts` with interceptors; create `services/{auth,invoices,customers,...}.ts`.
4. Restructure `app/` into `(auth)` and `(app)` groups with the five tabs.
5. Build the UI kit and the entitlement hooks.

---

## 9. Progress

**Phase 0 + 1 — done** (bundles for iOS, `tsc` and `expo lint` clean; not yet exercised on a device/simulator).
- Auth: bearer token in `expo-secure-store`; login returns it when the request has `X-Client: mobile` (`accounts/api/views.py`, `views_invites.py`; tests in `accounts/tests_mobile_login.py`).
- Shell: root-layout route guards (signed out → `(auth)` + invite; signed in without a company → `company-setup`; otherwise tabs).
- Screens: login, signup (register → login), company setup, invite accept (`invoicepro://invite/<token>`), Home (dashboard KPIs), More, My Profile.
- Entitlements: `useFeature()` / `useCan()` from `authz/me/`; global "upgrade required" alert.
- Payments: "Plan & billing" opens `EXPO_PUBLIC_WEB_URL/billing` in the browser.

**Deferred / changed from the original plan**
- Google login — needs native OAuth client IDs; not started.
- Forgot password — the backend has no reset endpoint.
- Company switcher — a user belongs to exactly one company in the backend today, so there is nothing to switch.
- Skipped by decision: template editing.
- Token refresh — the access token lasts 50 days and there is no refresh endpoint; a 401 signs the user out.

**Phase 2 — done** (tsc / lint / iOS bundle clean; API sequence verified by `invoice/tests_mobile_flow.py`; not yet exercised on a device).
- Tabs: Home, Invoices, Customers, More (+ Vendors from More).
- Invoices: list (search, status filter, infinite scroll), detail, create, edit (header, add/remove items), duplicate, mark paid, delete, share PDF (native share sheet), send on WhatsApp.
- Line items follow the company's configured columns; maths is a port of the web `calculateProductTotals` (`lib/invoice-calc.ts`).
- Customers & vendors: list, search, add/edit/delete, picker with inline "add new" in the invoice form.
- Permission-gated actions (`invoice.create/update/delete`, `customer.manage`, `vendor.manage`, `whatsapp.send`).
- Not in Phase 2: editing an existing line item in place (remove + re-add instead), picking a PDF template (server default), per-customer detail/ledger screen, inventory picker in the item form (Phase 3), UPI QR toggle, custom header fields.

**Phase 3 — done** (tsc / lint / iOS bundle clean; API calls verified by `inventory/tests_mobile_flow.py`; not yet exercised on a device — barcode scanning in particular needs a real camera).
- More → Inventory (gated on the `inventory` plan feature + `inventory.manage`): product list with search and low-stock filter, add/edit/delete, categories, stock in/out with history.
- Barcode scan (`expo-camera`): a scanned code is matched against the SKU; found → opens the product, not found → offers to add it with the SKU prefilled.
- Invoices: "Pick from inventory" in the item form fills name/rate/GST/description by column title (same as web) and deducts stock when the invoice is saved; the deduction runs only after all lines saved, and failures are reported without failing the invoice.
- Deferred: product/line-item images (plan-gated `line_item_images` + company opt-in), legacy Suppliers screen (superseded by Vendors), whole-number stock only (matches the backend's integer stock).

**Phase 4 — done** (tsc / lint / iOS bundle clean; every endpoint shape the app reads is pinned by `invoice/tests_mobile_reports.py`; not yet exercised on a device — camera/photo capture, file sharing and the OCR upload in particular).
- More → Reports (needs `advanced_reports` + `report.view`): sales report (KPIs, trend, top customers, status/method/state breakdowns), cash flow (daily/weekly/monthly), GST summary, customer & vendor ledgers (ageing, statement; also reachable from a customer/vendor screen), CSV export of invoices (needs `bulk_export`) via the share sheet. Charts are plain Views — no chart dependency.
- More → Purchases (needs `purchases_invoice`): summary, purchase-bill list, add/edit bills (the invoice form now handles vendor-side bills), and **Scan a bill**: camera / photo library / PDF → upload → job list with plan usage, auto-polling while a job is processing.
- Server side: added `invoice.view` permission check to `bulk_export`; fixed `purchase-summary` always showing "-" for vendor; `invoice/tests_report_gates.py` proves plan-gate (`upgrade_required`), permission-gate and tenant isolation on all report, export and OCR endpoints. `FEATURES.md` §1.5 corrected — most of the gaps it listed were already closed.
- Not in Phase 4: reviewing/editing the OCR-extracted fields before they become a bill (the pipeline creates the bill itself; edit it from Purchases), purchase-register view, scheduled reports, PDF export of reports.

**Phase 5 — done** (tsc / lint / iOS bundle clean; every endpoint shape the app reads is pinned by `invoice/tests_mobile_settings.py`; not yet exercised on a device). The More tab is now grouped into Business / Settings / Account.
- **Plan & billing** (read-only; payment stays on the web as decided): current plan and status, renewal/cancel/scheduled-change notices, plan comparison with prices and limits, payment history, and a "manage on the web" button.
- **WhatsApp**: choose the sending number (shared vs own, with plan availability and daily limits), pick the default invoice template for WhatsApp sends, see whether an own number is connected, list and sync Meta message templates, send a test message. Connecting a business number needs Meta sign-in and stays on the web.
- **Team & access** (admins; invites need `user.invite`): members with their roles (tap to assign/unassign roles — the "last admin" guard is enforced by the server), invites (send, resend, revoke, share link), read-only roles list, activity log.
- **Invoice templates**: my templates (set default), gallery with category filter, sample PDF preview, add to my templates. Layout editing stays on the web.
- **Invoice numbering**: enable, template with token chips and live preview, reset period, next number.
- **Invites on a phone**: login screen has "Have an invite link?" — paste the emailed link (or bare token) and the app opens the invite flow. True tap-to-open from the email needs domain-verified universal/app links (see below).
- Not in Phase 5: custom roles/groups and per-user permission overrides (web), connecting a WhatsApp Business account, template/numbering for purchases, scheduled plan changes.

**Phase 6 — done in code; store submission is blocked on items only you can supply** (see `MobileApp/RELEASE.md`). Checks: tsc / lint / 38 Jest tests / iOS + Android bundles all clean; 325 backend tests pass apart from 3 failures in `accounts.tests.UserModelTestCase` that also fail on the original code.
- **First real run.** The app was exercised end to end in a browser (web build) against a live backend on a throwaway in-memory database: login, dashboard, invoice list/detail, creating an invoice with an item, mark as paid, reports, purchases, inventory, team, numbering, billing, WhatsApp. It found and fixed real bugs that compilation could not: outline/danger buttons collapsing to a sliver (`flex: 1` on a fixed-height control), squashed filter chips, a dark navigation theme over light screens, a phantom ₹1 on blank item lines, and the app carrying on with no permissions (misleading "No access" screens) when the account failed to load. It has still not run on a phone or simulator (no Xcode/Android SDK here).
- **Resilience.** Last-known account/permissions are cached so the app opens offline; if nothing is cached and the account can't load, a "Couldn't load your account — Try again" screen replaces the old silent failure. Permissions refresh when the app returns to the foreground. An `ErrorBoundary` replaces blank crashes.
- **Offline.** Everyday read screens are cached for 24 h (persisted query cache, allow-listed keys only); offline banner; invoices finished offline are saved as drafts (owner-tagged, survive sign-out/expiry) under More → Drafts and sent later.
- **App lock** (Face ID / fingerprint, device passcode fallback, re-locks after 30 s in background) and **push notifications** (opt-in toggle; backend `DeviceToken` model + `/api/devices/` + Expo push sender; "Bill scanned" push when OCR completes; unregistered on sign-out). Backend migration `accounts/0014_devicetoken` must be deployed.
- **Accessibility** roles/labels/state on buttons, chips, switches, fields and badges; **light-only theme** (decision recorded in RELEASE.md).
- **Release config:** bundle ids, `eas.json` (development/preview/production), deep links (`+native-intent` maps `/app/invite/<token>`; `.well-known` templates in `release/`), permission strings, light `userInterfaceStyle`. Web build fixed (`import.meta` via `babel.config.js`; notification calls guarded) so `npm run web` works.
- **Tests:** Jest (calc port, invite-link parsing, date ranges, error mapping, offline detection, session bootstrap); backend `accounts/tests_push.py`.
- **Blockers/decisions:** in-app **account deletion** (required by both stores; does not exist anywhere yet), developer accounts, real icon/splash, `eas init`, store listing, Android package id vs the existing TWA, crash reporting DSN.
