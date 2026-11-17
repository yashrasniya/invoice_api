# GST filing roadmap

How our GST filing support compares with Zoho Books, what we can build now with no outside
registration, and what needs one first. Numbers (#) match the feature comparison shared on
17 Nov 2026. The Zoho column comes from general knowledge of Zoho Books India, not a live check.

**Size:** S ≈ 1 day · M ≈ 2–4 days · L ≈ 1–2 weeks (rough, before detailed planning).

---

## Where we stand today

**Already built:**
- CGST+SGST vs IGST on PDFs and reports (#5, #32).
- GST summary with data-quality warnings.
- GSTR-1 summary, portal JSON and pre-filing errors (#13–15). The JSON has not been test-uploaded to the portal yet.
- Credit/debit notes that move the GST liability (#29).
- Server-side tax recalculation.
- Place of supply 96 for exports.
- GSTIN checksum check, used inside GSTR-1 only.

---

## ✅ Can do now (no outside registration or API access)

### Phase 1: Stop bad data at entry

Mostly validation and form work, and the highest value per day spent.

| # | Feature | Summary of approach | Size |
|---|---|---|---|
| 1 | GSTIN format + checksum on save | Use `gstin_error()` in the customer/vendor serializers and in the app/web forms; show the reason inline. | S |
| 11 | GSTIN ↔ state mismatch | Fill the state from the GSTIN prefix on save; reject or warn when they differ. | S |
| 12 | Invoice number rules on save | Enforce ≤16 characters, allowed characters and uniqueness within the FY in `InvoiceSerializer` (today only GSTR-1 checks this). | S |
| 4 | Place of supply auto-filled | Prefill it from the customer's state on the invoice form and show it; still editable. | S |
| 6 | HSN/SAC as a real field | Add `hsn_code` to inventory products and line items. Keep reading the free-text column as a fallback; validate 4/6/8 digits. Offer a bundled HSN list (from the public GSTN HSN master) for search. | M |
| 7 | Item defaults | Inventory item carries its rate + HSN + unit; picking it fills the line. | S |

**Status: Phase 1 implemented 17 Nov 2026** (tests in `invoice/tests_gst_phase1.py`). HSN search is
still deferred, see below.

#### Phase 1: detailed plan (approved 17 Nov 2026)

**#1 + #11: GSTIN and state on customers and vendors**
- `CompanySerializer` / `VendorSerializer.validate()`: when `gst_number` is non-blank, normalise it
  (upper-case, no spaces) and reject it if `gstin_error()` fails (format, state prefix, check character).
- The state comes from the GSTIN: fill `state_code` and `state` from the prefix. If the request also
  sends a *different* state code, return 400: "GSTIN is registered in X, not Y".
- Company onboarding (`UserCompanies` serializer) also gets the check-character test.
- App party form: state becomes a state picker (was free text + code). Typing a complete valid GSTIN fills
  and locks the state; an invalid one shows the reason inline before saving.
- Web customer + vendor forms: same live check and fill, using a JS port of the check-character algorithm.
- Existing bad GSTINs aren't touched until that customer is next edited (the save then asks for a fix).

**#12: Invoice-number rules on save (sales only; purchase numbers are the vendor's)**
- `InvoiceSerializer.validate()`: when a sales invoice is created or its number changes, the number must be
  ≤16 characters of letters, digits, `-`, `/`, and unique (case-insensitive) among the company's sales
  invoices in that financial year. Blank stays allowed (GSTR-1 still flags it).
- Numbering settings: a template whose preview exceeds 16 characters becomes an error (was a warning),
  so auto-numbers always pass.
- App/web show the server message on the number field.

**#6 + #7: HSN/SAC, unit and item defaults**
- `inventory.Product` gets `hsn_code` (4/6/8 digits, optional) and `unit` (GST unit code, e.g. NOS, KGS);
  migration; serializer validation.
- Line items keep HSN in the bill's HSN column (that's what templates print), but a value typed into
  an HSN-titled column is now validated server-side (400 on a bad code), like the GST-rate column.
- Picking an inventory item fills Rate, GST, HSN and Unit columns (the column match is shared and
  title-based, the same as the server's). App inventory form + web inventory form get HSN + unit fields.
- GSTR-1: a company with no HSN column gets one clear error ("add an HSN/SAC column to your bill
  fields") instead of one per line.
- *Deferred:* HSN search/lookup needs GSTN's HSN master file downloaded and bundled; that needs your OK.

**#4: Place of supply, visible and automatic**
- App and web invoice forms: once a customer is picked, the field shows the state it will use
  ("Maharashtra (27), from the customer") and whether the invoice is intra-state (CGST + SGST) or
  inter-state (IGST), compared with the company's state. It can still be overridden.

**Tests:** serializer tests for each rule (valid, typo, mismatch, duplicate in FY, same number in a
different FY, purchase exempt), the inventory HSN/unit, the HSN cell validation and the GSTR-1 message;
mobile typecheck + jest; web build.

### Phase 2: Model the GST cases we don't represent yet

| # | Feature | Summary of approach | Size |
|---|---|---|---|
| 3 | GST treatment per customer | New field: registered / composition / unregistered / consumer / overseas / SEZ / deemed export. Default it from the GSTIN; GSTR-1 classifies by it instead of guessing. | M |
| 8 | Nil-rated / exempt / non-GST | Per-line tax category with an exemption reason; GSTR-1 Table 8 splits the nil, exempt and non-GST columns. | M |
| 22 | SEZ / deemed exports in GSTR-1 | Follows #3: invoice type SEWP/SEWOP/DE in the B2B table. | S |
| 33 | Export under LUT | Store the LUT number + validity on the company; print it on export invoices; choose WPAY/WOPAY explicitly. | S |
| 9 | Reverse charge | Invoice flag; "Reverse charge: Yes" on the PDF; `rchrg: Y` in GSTR-1; liability moves to 3B 3.1(d) for RCM purchases. | M |
| 10 | Cess | Optional cess rate per item/line; carried through PDF, GSTR-1 (`csamt`) and 3B. | M |

### Phase 3: More returns from the same data

| # | Feature | Summary of approach | Size |
|---|---|---|---|
| 17 | GSTR-3B preparation | Build tables 3.1, 3.2 and 4 from sales, purchases and notes (reusing the GSTR-1 builder and the GST summary); show what to type into the portal. No direct filing. | M |
| 28 | Ineligible input credit | Per-purchase-line "ITC eligible / blocked (17(5)) / reversal"; feeds 3B table 4. | M |
| 19 | Quarterly filing + monthly invoice upload (IFF) | Mark the company as a monthly or quarterly filer; for the first two months of a quarter, produce a B2B-only JSON. | S |
| 21 | Advances (11A/11B) | Record advance receipts that carry GST; adjust them against later invoices; report both tables. | L |
| 20 | Amendments (9A/9C/10/11) | Editing an invoice from an already-filed period creates an amendment record instead of changing history; GSTR-1 reports it in the amendment tables. Depends on #23. | L |
| 24 | Annual return (GSTR-9) data | Yearly roll-up of the monthly GSTR-1/3B figures, as a report only. | M |

### Phase 4: Control and reconciliation

| # | Feature | Summary of approach | Size |
|---|---|---|---|
| 23 | Lock filed periods | "Mark GSTR-1 filed for <period>" stores a lock; invoices and notes in it become read-only (admin override is logged in the audit log). | M |
| 26 | Match purchases against GSTR-2B | The user downloads their GSTR-2B JSON from the portal and uploads it; we match by supplier GSTIN + invoice number + amount and show matched / mismatched / missing from books / missing from 2B. | L |
| 34 | TDS/TCS under GST | Record GST TDS deducted by government customers (and TCS by e-commerce operators) and show it as a credit. | M |
| 35 | Multiple GSTINs per company | A company has several registrations (branches); every invoice picks one; all GST reports run per GSTIN. Touches almost everything, so do it last. | L |

**Suggested order:** Phase 1, then #3 and #8, then #17, then #23, then the rest by demand.

---

## ❌ Can't do now (needs registration, credentials or a partner first)

| # | Feature | Why not | What it would take |
|---|---|---|---|
| 14 | Confirm the GSTR-1 JSON is accepted | Needs a real GSTIN login on the portal / offline tool. | You (or a pilot customer) do one test upload; we fix whatever it rejects. |
| 2 | Fetch business details from the GST portal by GSTIN | The GST portal's API is only open to licensed GST filing providers (GSPs). | A GSP contract (e.g. ClearTax, Masters India, IRIS) and their API keys. |
| 16, 18 | File GSTR-1 / GSTR-3B directly | Filing is only possible through a GSP, with the taxpayer's OTP authorising API access. | GSP contract plus an OTP consent flow in the app. |
| 27 | Invoice Management System (accept/reject supplier invoices) | Lives on the portal; API access is GSP-only. | Same GSP contract. Until then, users do it on the portal. |
| 30 | e-Invoicing (IRN + signed QR) | IRNs are issued by the government e-invoice system (IRP) to registered API users or via GSPs. Mandatory only above the turnover limit. | Register as an API user on the IRP or go through a GSP; sandbox testing; build the IRP JSON. |
| 31 | e-Way bill generation | The national e-way bill system (NIC) API needs registration as an API user or a GSP. | Register for EWB API access or use a GSP; capture transport details on the invoice. |
| 26 (automatic) | 2B fetched automatically | Same GSP limitation. | GSP contract. The manual-upload version is in Phase 4. |

**One decision unlocks most of this table:** picking a GSP partner. One contract typically covers
GSTIN lookup, GSTR-1/3B filing, 2B/IMS fetch, and often e-invoice and e-way bill too.

---

## Next step

When a phase or a set of items is approved, a detailed implementation plan is written for it
first: model changes, migrations, API, app/web screens and tests.
