/** GST state codes — mirrors invoice_api/accounts/gst_utils.py. */
export const GST_STATES: { code: number; name: string }[] = [
  [1, 'Jammu and Kashmir'], [2, 'Himachal Pradesh'], [3, 'Punjab'], [4, 'Chandigarh'], [5, 'Uttarakhand'],
  [6, 'Haryana'], [7, 'Delhi'], [8, 'Rajasthan'], [9, 'Uttar Pradesh'], [10, 'Bihar'], [11, 'Sikkim'],
  [12, 'Arunachal Pradesh'], [13, 'Nagaland'], [14, 'Manipur'], [15, 'Mizoram'], [16, 'Tripura'],
  [17, 'Meghalaya'], [18, 'Assam'], [19, 'West Bengal'], [20, 'Jharkhand'], [21, 'Odisha'], [22, 'Chhattisgarh'],
  [23, 'Madhya Pradesh'], [24, 'Gujarat'], [26, 'Dadra and Nagar Haveli and Daman and Diu'],
  [27, 'Maharashtra'], [29, 'Karnataka'], [30, 'Goa'], [31, 'Lakshadweep'], [32, 'Kerala'], [33, 'Tamil Nadu'],
  [34, 'Puducherry'], [35, 'Andaman and Nicobar Islands'], [36, 'Telangana'], [37, 'Andhra Pradesh'],
  [38, 'Ladakh'], [97, 'Other Territory'],
].map(([code, name]) => ({ code: code as number, name: name as string }));

/**
 * Choices for an invoice's place of supply: every state plus 96 "Other Countries", the place of supply of an
 * export. 96 is never a GSTIN prefix, so it stays out of GST_STATES (which GSTINs are parsed against).
 */
export const PLACE_OF_SUPPLY_STATES: { code: number; name: string }[] = [...GST_STATES, { code: 96, name: 'Other Countries' }];

const GSTIN_RE = /^(\d{2})[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export const normalizeGstin = (v: string) => v.replace(/\s+/g, '').toUpperCase();

/** The state a complete, well-formed GSTIN belongs to, or null while it is still being typed / invalid. */
export function stateFromGstin(raw: string) {
  const gstin = normalizeGstin(raw);
  const m = GSTIN_RE.exec(gstin);
  return m ? GST_STATES.find((s) => s.code === Number(m[1])) ?? null : null;
}

export const isValidGstin = (raw: string) => stateFromGstin(raw) !== null;

/**
 * Whether a line-item column holds the GST rate. Mirrors invoice_api/gst.py `is_gst_column`, which the server
 * recomputes totals with — so a column titled "GST %" or "Tax" is read as tax rather than multiplied into the total.
 */
const GST_COLUMN_KEYS = new Set(['gst', 'gstrate', 'gstpercent', 'gstpercentage', 'tax', 'taxrate', 'taxpercent', 'taxpercentage', 'igst']);
export const isGstColumn = (title: string | null | undefined) => GST_COLUMN_KEYS.has(String(title || '').toLowerCase().replace(/[^a-z]/g, ''));
