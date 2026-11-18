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
- GSTR-1 summary, portal JSON and pre-filing errors (#13–15), in the app (Reports → GSTR-1) and on the
  web (Reports → GSTR-1, `/gstr1`). The JSON has not been test-uploaded to the portal yet.
- GSTR-3B preparation and GSTR-9 figures (Reports → GSTR-3B / GSTR-9, app and web); ITC eligibility
  on purchases; quarterly (QRMP) filing with the IFF (Phase 3).
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

**Status: Phase 2 implemented 17 Nov 2026** (tests in `invoice/tests_gst_phase2.py`). #10 cess dropped,
see below. Web bill lines pick up an inventory item's 0% category since 17 Nov 2026.

#### Phase 2: detailed plan (approved 17 Nov 2026)

**#3 + #22: GST treatment per customer/vendor**
- `gst_treatment` on Customers and Vendor: `registered`, `composition`, `unregistered`, `consumer`,
  `overseas`, `sez`, `deemed_export`. Migration backfills it: GSTIN → registered, none → unregistered.
- On save, a blank treatment is derived the same way. Registered, composition, SEZ and deemed export
  require a GSTIN; unregistered, consumer and overseas must not have one. Overseas sets the state to
  96 (Other Countries).
- `supply_type()`: SEZ and overseas are always inter-state (IGST), whatever the state codes say
  (IGST Act s.7(5)).
- GSTR-1 classifies by treatment: registered/composition → B2B `R`; SEZ → B2B `SEWP` (with tax) or
  `SEWOP` (without tax, needs a LUT); deemed export → B2B `DE`; overseas → 6A exports. Rows saved
  before this field existed fall back to "has a GSTIN?" and place of supply 96.
- App + web party forms: a treatment picker that follows the GSTIN as it's typed.

**#33: Export / SEZ under LUT**
- Company gets `lut_number`, `lut_valid_from`, `lut_valid_to` (an LUT is filed per financial year).
- GSTR-1: an export or SEZ invoice with zero tax needs a LUT valid on the invoice date, else an error.
  With tax → `WPAY` / `SEWP`.
- PDF: a `lut_declaration` field ("Supply meant for export / to SEZ under LUT No. … without payment of
  IGST") for templates to print.
- Web company form gets the LUT fields; the app gets them on its GST settings screen (More → GST settings,
  `company/gst-settings/`).

**#8: Nil-rated / exempt / non-GST lines**
- `tax_category` on bill lines and inventory items: `taxable` (default), `nil`, `exempt`, `non_gst`.
  Only meaningful at 0%: a 0% `taxable` line counts as nil-rated, which is what 0% means.
- GSTR-1 Table 8 fills `nil_amt` / `expt_amt` / `ngsup_amt` per category. Non-GST lines stay out of
  Table 12. A non-taxable category on a line with a non-zero rate is an error.
- App: line-item screen offers the category when the rate is 0; inventory items carry a default.
  Web: inventory items carry it, and picking an item applies it.
- *Not covered:* a "bill of supply" document type for exempt-only sales.

**#9: Reverse charge**
- `reverse_charge` flag on invoices. On such an invoice the supplier collects no GST:
  `gst_final_amount` = tax the recipient pays, `total_final_amount` = amount payable to the supplier
  (excludes that tax). Line totals still include tax; the invoice total subtracts it.
- One helper gives taxable value everywhere (`total` if RCM, else `total − gst`): GST summary, tax
  split, list serializer, PDF and GSTR-1.
- GST summary: RCM sales are left out of your output tax (the buyer pays it). RCM purchases add
  "payable under reverse charge" (must be paid in cash) and count as input credit.
- GSTR-1: `rchrg: "Y"`; allowed only on B2B invoices (error otherwise).
- PDF: `reverse_charge` = Yes/No and `rcm_tax_amount` for templates; the footer total excludes the tax.
- App + web invoice forms: a "Reverse charge" switch.
- *Unverified:* whether the portal expects GSTR-1 `val` on RCM invoices with or without the tax. It's
  sent with tax included; confirm with the first real upload.

**#10: Cess, dropped.** Compensation cess ended on 1 Feb 2026 (GST 2.0 had already removed it from
everything except tobacco in Sept 2025). It was replaced by excise duty and a health cess that sit
outside GST, so there's nothing left to report in GSTR-1 for current invoices.

**Tests:** treatment validation and derivation; GSTR-1 for SEZ (with and without payment), deemed
export, overseas without a state, LUT missing or expired, nil/exempt/non-GST in Table 8, RCM in B2B
and RCM rejected on B2C; RCM totals and GST-summary netting; app typecheck + jest; web build.

### Phase 3: More returns from the same data

| # | Feature | Summary of approach | Size |
|---|---|---|---|
| 17 | GSTR-3B preparation | Build tables 3.1, 3.2 and 4 from sales, purchases and notes (reusing the GSTR-1 builder and the GST summary); show what to type into the portal. No direct filing. | M |
| 28 | Ineligible input credit | Per-purchase-line "ITC eligible / blocked (17(5)) / reversal"; feeds 3B table 4. | M |
| 19 | Quarterly filing + monthly invoice upload (IFF) | Mark the company as a monthly or quarterly filer; for the first two months of a quarter, produce a B2B-only JSON. | S |
| 21 | Advances (11A/11B) | Record advance receipts that carry GST; adjust them against later invoices; report both tables. | L |
| 20 | Amendments (9A/9C/10/11) | *Moved to Phase 4, after #23.* | L |
| 24 | Annual return (GSTR-9) data | Yearly roll-up of the monthly GSTR-1/3B figures, as a report only. | M |

**Status: Phase 3 partly implemented 17 Nov 2026** (#17, #28, #19, #24; tests in
`invoice/tests_gst_phase3.py`). #21 and #20 are not started, see below.

#### Phase 3: detailed plan (17 Nov 2026)

**One source for every return.** The GSTR-1 builder already classifies each invoice and note. It now
also keeps a *ledger*: one entry per classified amount, with its kind (B2B, B2C, export with/without
IGST, SEZ with/without IGST, deemed export, reverse charge, nil, exempt, non-GST, note), taxable value,
IGST / CGST / SGST, place of supply and whether it is an inter-state supply to an unregistered or
composition buyer. GSTR-3B and GSTR-9 add up that ledger, so the three returns can't disagree.
An invoice GSTR-1 can't classify (an error there) is left out of all three, and 3B/9 say so.

**#28: Input credit eligibility**
- `itc_eligibility` on purchase invoices: `eligible` (default), `blocked` (s.17(5), e.g. motor cars,
  food, personal use: never claimable) or `reversal` (claimable later, e.g. supplier hasn't paid tax).
  A purchase line can override it (`Product.itc_eligibility`, blank = follow the invoice).
- 3B Table 4: 4A holds all credit; blocked goes to 4B(1), reversal to 4B(2); 4C = net.
- App and web: the purchase bill gets the choice, and each line can override it (line-item screen /
  line popup).

**#17: GSTR-3B preparation** (`GET /api/gstr3b/?period=`, a report: no file, no filing)
- 3.1(a) taxable outward (B2B, B2C, deemed exports, notes), 3.1(b) zero-rated (exports, SEZ),
  3.1(c) nil-rated + exempt, 3.1(d) inward reverse charge (purchases flagged RCM, and services bought
  from overseas suppliers), 3.1(e) non-GST. Supplies where the *buyer* pays under reverse charge are
  shown separately: they're not your liability.
- 3.2 inter-state supplies to unregistered and composition buyers, by state.
- 4 ITC: 4A(1) import of goods, 4A(2) import of services, 4A(3) inward reverse charge, 4A(5) all other
  (purchases + vendor notes), 4B(1)/(2), 4C. A purchase with tax but no supplier GSTIN is left out of
  ITC (credit needs a tax invoice from a registered supplier) and flagged; reverse-charge purchases
  are exempt from that rule.
- 5 inward exempt, nil and non-GST supplies (0% lines, composition suppliers), inter/intra.
- 6.1 payment: liability per head, set off with credit in the legal order (IGST credit first: IGST, then
  CGST/SGST; CGST and SGST credit only after that, never against each other; Rule 88A), the cash to
  pay, and reverse-charge tax (always cash). Credit left over is carried forward.

**#19: Quarterly filers (QRMP) and IFF**
- Company setting `gst_filing_frequency`: monthly (default) or quarterly. Web company form; app GST settings
  screen.
- Quarterly filer, first or second month of a quarter: GSTR-1 becomes the **IFF** (B2B invoices, SEZ,
  deemed exports and their notes only); the file has just `b2b` and `cdnr`. Warning above ₹50 lakh
  of B2B value in the month (the IFF limit).
- Quarterly filer, third month alone: refused ("filed in the quarterly return").
- Quarterly filer, the quarter: by default leaves out the B2B invoices and notes of the first two months,
  which were already uploaded in the IFF; a switch includes them (if the IFF wasn't used).

**#24: GSTR-9 data** (`GET /api/gstr9/?fy=2025`, a report)
- The FY's ledger in GSTR-9's tables: 4 (B2C, B2B, exports and SEZ with IGST, deemed exports, inward
  reverse charge, credit/debit notes), 5 (exports and SEZ without IGST, buyer-paid reverse charge,
  exempt, nil, non-GST), 6 (ITC: total, inward reverse charge, imports), 7 (blocked → 7E, reversal → 7H)
  and 17 (HSN summary of outward supplies).
- From your books, not from returns as filed: figures differ where returns were amended on the portal.
  6B isn't split into inputs / capital goods / input services (not recorded).

**Not in this phase**
- **#21 Advances (11A/11B):** there's no way to record a payment yet. The `Payment` model exists, but
  no API or screen creates one (only demo data does); credit/debit notes are the same. Recording
  receipts comes first; then an advance is a receipt with a GST rate, reported in 11A until an invoice
  adjusts it (11B). Advances for goods carry no GST (notification 66/2017), so it's services only.
- **#20 Amendments:** needs #23 (filed-period lock) to know what was already filed. Moves to Phase 4,
  after #23.

**Tests:** ledger → 3B tables on a mixed month (B2B, B2C inter/intra, export, SEZ, nil/exempt/non-GST,
RCM both ways, notes); ITC eligibility and line override; no-GSTIN supplier left out; import of
services as RCM; set-off order cases; IFF month, refused third month, quarter with and without the
IFF months; GSTR-9 table totals over a FY; app typecheck + jest; web build.

### e-Way bill (#31), Phase A: offline bulk JSON

#31 splits in two. **Phase A** needs no registration: the e-way bill portal (ewaybillgst.gov.in)
accepts a bulk-upload JSON, so we build that file (as with GSTR-1), the user uploads it, and types the
EWB number back in. **Phase B** (generate/cancel/extend/update Part B over the API) stays in the
"Can't do now" table: it needs the GSP decision.

**Status: Phase A implemented 17 Nov 2026** (tests in `invoice/tests_eway.py`; flow in
`docs/invoice-generation.md` → "E-way bills"). Not yet test-uploaded on the portal. The ship-to block
lives on `EwayBill`, not on the invoice. `INTRA_STATE_LIMITS` is shipped empty (₹50,000 everywhere)
until each state's figure is checked.

#### Phase A: detailed plan (approved 17 Nov 2026)

**Data gaps filled**
- `UserCompanies.pincode` (dispatch-from PIN). Optional ship-to block on the invoice (name, address,
  state code, PIN) → transaction type "bill-to / ship-to" when used.
- HSN / qty / unit per line reuse the GSTR-1 line extractor; a missing HSN or unit is an error.

**Model: `EwayBill`** (one per invoice; `invoice/eway.py` holds the rules)
- Part A: supply type (outward/inward), sub-type (supply, export, job work, SKD/CKD, …), document type
  (tax invoice / bill of supply), transaction type, from/to PIN + state, distance (km).
- Part B: mode (road/rail/air/ship), vehicle no., vehicle type (regular / over-dimensional),
  transporter GSTIN or TRANSIN + name, transport doc no. + date.
- Result: `ewb_number`, `ewb_date`, `valid_until`, `status` (draft/generated/cancelled), `source`
  (manual/api), `raw`.

**Rules**
- "Needs an e-way bill": goods lines (HSN not `99…`) and consignment value (taxable + tax, without
  exempt / non-GST lines) above ₹50,000; per-state intra-state overrides in a small table. A hint,
  never a block. Reports list invoices that need one and don't have it.
- Validity: 1 day per 200 km (20 km for over-dimensional cargo); a day ends at the next midnight.
- Checks: vehicle number format, transporter GSTIN checksum, distance 1–4000 km, PIN matches state,
  document not older than the portal's limit.

**API**
- `GET/PUT /api/eway/<invoice_id>/`: the invoice's e-way bill details + "needed" verdict; saving the
  EWB number sets status `generated` and `valid_until`.
- `GET /api/eway/json/?ids=…`: bulk-upload JSON, or the list of errors per invoice.
- Gate: plan feature `eway_bill`; editing needs the invoice-edit permission; changes are audit-logged.

**PDF:** EWB number, date, vehicle and validity in the invoice header block (both renderers).

**Screens:** app invoice detail gets a "Transport / e-way bill" section, a "needs e-way bill" banner and
a JSON share action; web invoice page the same, plus bulk export.

**Not in this phase:** delivery challans (stock transfer, job work, on approval) — no challan document
exists yet; inward EWBs for unregistered suppliers (the model allows it, screens come later).

**Before relying on it:** one test upload of the JSON on the portal, as for GSTR-1 (#14).

**Tests:** need-EWB verdict (goods vs services, ₹50k edge, exempt lines, state override); validity at
day boundaries and ODC; each JSON error; bill-to/ship-to output; PDF block; gate and permission;
app typecheck + jest; web build.

### Phase 4: Control and reconciliation

| # | Feature | Summary of approach | Size |
|---|---|---|---|
| 20 | Amendments (9A/9C/10/11) | Editing an invoice from an already-filed period creates an amendment record instead of changing history; GSTR-1 reports it in the amendment tables. Needs #23 first. | L |
| 23 | Lock filed periods | "Mark GSTR-1 filed for <period>" stores a lock; invoices and notes in it become read-only (admin override is logged in the audit log). | M |
| 26 | Match purchases against GSTR-2B | The user downloads their GSTR-2B JSON from the portal and uploads it; we match by supplier GSTIN + invoice number + amount and show matched / mismatched / missing from books / missing from 2B. | L |
| 34 | TDS/TCS under GST | Record GST TDS deducted by government customers (and TCS by e-commerce operators) and show it as a credit. | M |
| 35 | Multiple GSTINs per company | A company has several registrations (branches); every invoice picks one; all GST reports run per GSTIN. Touches almost everything, so do it last. | L |

**Suggested order:** Phase 1, then #3 and #8, then #17, then #23, then the rest by demand.
Phases 1–2 and most of Phase 3 are done; next up is recording payments (unblocks #21), then #23 → #20.

---

## ❌ Can't do now (needs registration, credentials or a partner first)

| # | Feature | Why not | What it would take |
|---|---|---|---|
| 14 | Confirm the GSTR-1 JSON is accepted | Needs a real GSTIN login on the portal / offline tool. | You (or a pilot customer) do one test upload; we fix whatever it rejects. |
| 2 | Fetch business details from the GST portal by GSTIN | The GST portal's API is only open to licensed GST filing providers (GSPs). | A GSP contract (e.g. ClearTax, Masters India, IRIS) and their API keys. |
| 16, 18 | File GSTR-1 / GSTR-3B directly | Filing is only possible through a GSP, with the taxpayer's OTP authorising API access. | GSP contract plus an OTP consent flow in the app. |
| 27 | Invoice Management System (accept/reject supplier invoices) | Lives on the portal; API access is GSP-only. | Same GSP contract. Until then, users do it on the portal. |
| 30 | e-Invoicing (IRN + signed QR) | IRNs are issued by the government e-invoice system (IRP) to registered API users or via GSPs. Mandatory only above the turnover limit. | Register as an API user on the IRP or go through a GSP; sandbox testing; build the IRP JSON. |
| 31 (Phase B) | e-Way bill generation over the API | The national e-way bill system (NIC) API needs registration as an API user or a GSP. Phase A (transport details + bulk-upload JSON) is done. | Register for EWB API access or use a GSP; then generate / cancel / update Part B / extend from the app. |
| 26 (automatic) | 2B fetched automatically | Same GSP limitation. | GSP contract. The manual-upload version is in Phase 4. |

**One decision unlocks most of this table:** picking a GSP partner. One contract typically covers
GSTIN lookup, GSTR-1/3B filing, 2B/IMS fetch, and often e-invoice and e-way bill too.

---

## Next step

When a phase or a set of items is approved, a detailed implementation plan is written for it
first: model changes, migrations, API, app/web screens and tests.
