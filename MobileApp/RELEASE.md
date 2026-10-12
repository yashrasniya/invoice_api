# Releasing Invoice Pro (mobile)

What is built, what is verified, and what is still needed before the stores will accept it.

## 1. Blockers (the stores will reject the app without these)

| # | Blocker | Why | Who/what |
|---|---|---|---|
| 1 | **In-app account deletion** | Apple (guideline 5.1.1(v)) and Google Play both require apps that let people create an account to let them delete it from inside the app. Nothing exists yet — not in the API, the web app, or the mobile app. | Needs a product decision first: deleting a company owner touches invoices you may have to keep for GST. Options: delete the *user* and keep the company's records, or a "request deletion" flow that you process. |
| 2 | **Developer accounts** | Apple Developer Program (US$99/yr) and Google Play Console (US$25 once). | You |
| 3 | **Real icon & splash** | `assets/images/*` are still the Expo starter artwork. | Design — 1024×1024 icon, Android adaptive foreground/background/monochrome, splash mark |
| 4 | **EAS project** | Push tokens and builds need a project id: run `npx eas-cli init` (writes `extra.eas.projectId` into `app.json`). | You, once logged in to Expo |
| 5 | **Store listing material** | Screenshots, description, privacy-policy URL (the web app has one at `/app/privacy`), support email, age rating, data-safety / privacy-label answers (see §4). | You |

## 2. Decisions I made that you should confirm

- **Bundle id / package:** `com.orvine.invoice` (iOS and Android). The existing `mobile_app_bubblewrap/` TWA uses `com.yashadvertisinggroup.twa`. **If that TWA is already published on Google Play and you want this app to replace it for existing users, change `android.package` in `app.json` to the TWA's id and sign with the same key** — a different id is a different app. Decide this before the first Play upload; the id cannot change afterwards.
- **Light theme only.** The screens use a fixed light palette, so the app is locked to light mode (`userInterfaceStyle: "light"`, navigation theme forced). A proper dark mode means moving every screen onto theme tokens — a separate piece of work.
- **Payments stay on the web.** "Plan & billing" shows status and hands off to the browser. If you later sell subscriptions inside the iOS app, Apple expects in-app purchase for digital subscriptions; keep the hand-off out of the iOS flow's "buy" path (it is read-only today, which is the safe position).
- **Offline scope.** Everyday read screens (dashboard, invoices, customers/vendors, inventory) are cached for 24 h and shown offline; invoices finished offline are saved as drafts on the phone (More → Drafts) and sent later. Reports, billing and team data are never copied to the device.
- **Cached data is not encrypted.** The offline cache and drafts live in the app's private storage (AsyncStorage), protected by the OS sandbox and the optional App Lock, but not separately encrypted. The login token *is* in the Keychain/Keystore (`expo-secure-store`).
- `mobile_app_bubblewrap/` (the old Android wrapper around the website) is untouched. Retire it once the native app is live.

## 3. One-time setup

Run these from the `MobileApp` folder, one at a time. (Do not paste comments after a command — zsh treats `#` as part of the command at an interactive prompt.)

```bash
npm install -g eas-cli
```
(If that fails with a permissions error, use `npx eas-cli` in place of `eas` below.)

```bash
eas login
```
```bash
eas init
```
`eas init` creates the EAS project and writes its id into `app.json` (blocker 4). `eas credentials` is optional: EAS offers to create the iOS certificates / Android keystore the first time you build.

**Deep links (invite emails open the app).** Invite emails contain `https://invoice.orvine.in/app/invite/<token>`. For those to open the app instead of the browser, serve these two files at the **site root** (the nginx config, not the Vite app), filling the placeholders from `release/`:

| File to serve | Template | Fill in |
|---|---|---|
| `https://invoice.orvine.in/.well-known/apple-app-site-association` (no extension, `application/json`) | `release/apple-app-site-association.template.json` | your Apple Team ID |
| `https://invoice.orvine.in/.well-known/assetlinks.json` | `release/assetlinks.template.json` | SHA-256 of the app signing key (`eas credentials`, or Play Console → App integrity once enrolled in Play App Signing) |

`app/+native-intent.tsx` already maps `/app/invite/<token>` onto the app's `/invite/<token>` route. Until the files are live, the login screen's "Have an invite link?" (paste the link) works as a fallback.

**Backend.** Deploy the new migration (`accounts/0014_devicetoken`) and the `/api/devices/` endpoint before shipping push notifications. Expo's push service needs no key for basic use.

## 3b. Android push notifications (Firebase) — required for the Notifications toggle to work on Android

Without this the toggle shows "Push notifications are not set up for this version of the app yet" (the underlying error is `Default FirebaseApp is not initialized`). It is a one-time, ~10 minute setup in your Google account — no code changes needed (`app.config.js` picks the file up automatically):

1. Go to https://console.firebase.google.com → **Add project** (any name, e.g. "Invoice Pro"; Analytics can be off).
2. In the project: **Add app → Android**, package name **`com.orvine.invoice`** (must match exactly). Download **`google-services.json`** and put it in the `MobileApp/` folder (next to `app.json`). It is client configuration, not a secret.
3. Firebase → ⚙ **Project settings → Service accounts → Generate new private key**. This JSON **is a secret** — keep it out of git (already in `.gitignore`).
4. Give that key to Expo (it sends the pushes through Google): in `MobileApp/` run `eas credentials`, then **Android → production/preview profile → Google Service Account → Manage your Google Service Account Key for Push Notifications (FCM V1) → Upload a new service account key**.
5. Run `./release/prepare-build-dir.sh` and build again (§4). The Notifications toggle then registers the phone; completing an OCR scan sends a "Bill scanned" push.

iOS push needs an Apple Developer account (APNs key, which `eas credentials` creates for you) and is not set up yet.

## 4. Build & submit

**Build from the clean copy, not from the repo.** EAS packages the whole git repository. Here that (a) drops this app's `lib/` folder because the repo-wide `.gitignore` has a `lib/` rule, which fails the build with `Unable to resolve module @/lib/...`, and (b) can upload unrelated files from the repo (backend, sample data, the old Android wrapper's keystore). So build from a copy that contains only the app:

```bash
./release/prepare-build-dir.sh
```
```bash
cd ~/invoice-pro-build
```
```bash
EAS_NO_VCS=1 eas build --profile preview --platform android
```

Re-run `prepare-build-dir.sh` before every build to refresh the copy. All the `eas build` / `eas submit` commands below are meant to be run from that folder with `EAS_NO_VCS=1` in front.

```bash
eas build --profile preview --platform android     # installable APK for internal testing
eas build --profile preview --platform ios         # ad-hoc build (needs registered test devices)
eas build --profile production --platform all      # store builds (version auto-increments)
eas submit --profile production --platform ios     # TestFlight / App Store
eas submit --profile production --platform android # Play (use the internal track first)
```

Profiles live in `eas.json`. `production` and `preview` point at `https://invoice.orvine.in`; `development` points at a LAN address — edit it to your machine's IP, and use `eas build --profile development` for a dev client when you need native modules in Expo Go's blind spots (push tokens, background behaviour).

**Store questionnaires — what the app actually does:**
- *Data collected:* name, email, phone, company details, invoices and customer/vendor/inventory data the user enters (linked to the account); photos/camera only when the user scans a bill or product barcode (uploaded for extraction; not used for tracking). No ads, no third-party analytics SDKs, no tracking.
- *Permissions requested:* camera (barcode scan, bill photo), photo library (choose a bill), notifications (opt-in), Face ID / biometrics (opt-in app lock).
- Encryption: standard HTTPS only (`ITSAppUsesNonExemptEncryption: false`).

## 5. Before every release

```bash
cd MobileApp && npx tsc --noEmit && npx expo lint && npx jest      # types, lint, 38 unit tests
cd ../invoice_api && ../venv/bin/python manage.py test invoice.tests_mobile_settings invoice.tests_mobile_reports \
    invoice.tests_report_gates invoice.tests_mobile_flow inventory.tests_mobile_flow \
    accounts.tests_mobile_login accounts.tests_push                 # the API contract the app depends on
```

Then walk this on a **real phone** (nothing below can be exercised in a browser or in CI):
- [ ] Sign up → company setup → create an invoice → **Share PDF** opens the share sheet with a real PDF
- [ ] **Send on WhatsApp** (needs the WhatsApp config on the server)
- [ ] **Scan barcode** finds a product by SKU; unknown code offers to add it
- [ ] **Scan a bill** (camera + library + PDF) uploads and the job completes; the push notification arrives and tapping it opens the scan list
- [ ] **App lock**: enable, background for 30 s, return → asks for Face ID / fingerprint; wrong biometrics fall back to the device passcode
- [ ] **Offline**: airplane mode → dashboard/invoices still show; create an invoice → "Save draft" → re-connect → More → Drafts → Send now
- [ ] CSV export shares a file; the invite link (once the `.well-known` files are live) opens the app
- [ ] Android: back button/gesture behaves; iPad layout is acceptable (`supportsTablet` is on — turn it off in `app.json` if you do not want to design for it)

## 6. Known limits

- Crash reporting is not wired (no Sentry DSN yet). An unexpected render error shows a friendly "Try again" screen (`ErrorBoundary`) but is not reported anywhere. Adding `@sentry/react-native` needs a DSN from you.
- No token refresh: the access token lasts 50 days; after that the user is signed out and signs in again. Unsent drafts survive.
- The app has not been run on a physical device or simulator in development (no Xcode/Android SDK on the build machine). It was exercised end-to-end in a browser against a live backend; the native-only pieces (camera, biometrics, push, share sheet, deep links) are covered by the checklist above.
