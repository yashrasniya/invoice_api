import * as FileSystem from 'expo-file-system/legacy';
import api, { errorMessage } from './api';
import { addMovement } from './inventory';
import { getToken } from './token-storage';
import { calculateLine } from '@/lib/invoice-calc';
import { HeaderConfig, resolveHeader } from '@/lib/header-config';

export type Paged<T> = { count: number; next: string | null; previous: string | null; results: T[] };

/** A company-configured line-item column (the web "bill fields"). */
export type Column = {
  id: number;
  input_title: string;
  is_show: boolean;
  is_calculable: boolean;
  formula: string;
  on_with_out_gst_amount: boolean;
  presets: string | null;
  default_value: string | null;
};

export type LineProperty = { id: number; value: string | null; new_product_in_frontend: Column };
export type LineItem = { id: number; product_properties: LineProperty[]; gst_amount: string; total_amount: string };

export type PaymentStatus = 'unpaid' | 'partially_paid' | 'paid' | 'overdue';
export type PaymentMethod = 'cash' | 'upi' | 'bank_transfer' | 'cheque' | 'card' | 'other';

export type Invoice = {
  id: number;
  invoice_number: string | null;
  receiver: number | null;
  receiver_name: string;
  receiver_gst_number: string;
  vendor: number | null;
  vendor_name: string;
  vendor_gst_number: string;
  date: string | null;
  products: LineItem[];
  gst_final_amount: string | null;
  total_final_amount: string | null;
  invoice_type: 'sales' | 'purchase';
  payment_status: PaymentStatus;
  payment_method: PaymentMethod | null;
  due_date: string | null;
  /** GST state code of the place of supply; null means "the customer's state" */
  place_of_supply: number | null;
  /** the customer's state code, when they have one */
  receiver_state_code: number | null;
  customer_notes: string;
  terms: string;
};

export const STATUS_LABEL: Record<PaymentStatus, string> = {
  unpaid: 'Unpaid', partially_paid: 'Partially paid', paid: 'Paid', overdue: 'Overdue',
};
export const METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: 'Cash', upi: 'UPI', bank_transfer: 'Bank transfer', cheque: 'Cheque', card: 'Card', other: 'Other',
};

export type InvoiceType = 'sales' | 'purchase';
export type InvoiceFilters = { search?: string; payment_status?: PaymentStatus | ''; customer?: number; type?: InvoiceType };

export async function listInvoices(page: number, f: InvoiceFilters) {
  const { data } = await api.get<Paged<Invoice>>('invoice/', {
    params: {
      invoice_type: f.type ?? 'sales',
      page,
      page_size: 20,
      ...(f.search ? { search: f.search } : {}),
      ...(f.payment_status ? { payment_status: f.payment_status } : {}),
      ...(f.customer ? { customer: f.customer } : {}),
    },
  });
  return data;
}

export async function getInvoice(id: number) {
  const { data } = await api.get<Paged<Invoice>>('invoice/', { params: { id } });
  const inv = data.results[0];
  if (!inv) throw new Error('Invoice not found');
  return inv;
}

export const fetchColumns = async () => (await api.get<Column[]>('new/product/in/frontend/')).data;

export type NewLine = {
  values: Record<number, string>;
  /** set when the line was filled from an inventory product; stock is deducted on save */
  inventoryProductId?: number;
};

export type InvoiceInput = {
  /** the customer (sales) or vendor (purchase) id */
  party: number;
  date: string;
  invoice_number?: string;
  /** Header fields below are left out when the company hides them, so the server fills its own default. */
  payment_status?: PaymentStatus;
  payment_method?: PaymentMethod | null;
  due_date?: string | null;
  place_of_supply?: number | null;
  customer_notes?: string;
  terms?: string;
};

/** The company's header-field settings. Falls back to "everything shown" if they can't be read. */
export async function fetchHeaderConfig(): Promise<HeaderConfig> {
  try {
    const { data } = await api.get<{ fields?: Record<string, never> }>('invoice-header-config/');
    return resolveHeader(data?.fields);
  } catch {
    return resolveHeader(null);
  }
}

/** Totals for a set of new lines under the company's column config. */
export function totalsFor(lines: NewLine[], columns: Column[]) {
  let total = 0;
  let gst = 0;
  for (const l of lines) {
    const r = calculateLine(columns.map((c) => ({ column: c, value: l.values[c.id] ?? '' })), columns);
    total += r.total_amount;
    gst += r.gst_amount;
  }
  return { total, gst };
}

/**
 * A line item is three kinds of rows on the server: a Product, one
 * Product_properties row per column, and the link to the invoice. That takes
 * several calls; they are made in dependency order and the properties are
 * attached in a single update.
 */
export async function addLineItem(invoiceId: number, line: NewLine, columns: Column[]) {
  const calc = calculateLine(columns.map((c) => ({ column: c, value: line.values[c.id] ?? '' })), columns);
  const amounts = { gst_amount: calc.gst_amount.toFixed(2), total_amount: calc.total_amount.toFixed(2) };

  const { data: product } = await api.post<{ id: number }>('product/', { product_properties: '', ...amounts });
  await api.post(`invoice/${invoiceId}/product/add/`, { product_id: product.id });

  const ids: number[] = [];
  for (const c of columns) {
    const { data } = await api.post<{ id: number }>('product/properties/', {
      new_product_in_frontend: c.id,
      value: line.values[c.id] ?? '',
    });
    ids.push(data.id);
  }
  await api.post(`product/${product.id}/update/`, { product_properties: ids.join(','), ...amounts });
  return product.id;
}

/**
 * Deduct inventory for lines that came from an inventory product. Runs only after
 * every line was saved, so a rolled-back invoice never leaves stock changed.
 * Returns human-readable warnings instead of throwing: the invoice itself is already saved.
 */
export async function deductStock(invoiceId: number, lines: NewLine[], columns: Column[]) {
  const qtyCol = columns.find((c) => c.input_title === 'Quantity');
  const warnings: string[] = [];
  if (!qtyCol) return warnings;
  for (const l of lines) {
    if (!l.inventoryProductId) continue;
    const qty = Number(l.values[qtyCol.id]);
    if (!Number.isFinite(qty) || qty <= 0) continue;
    if (!Number.isInteger(qty)) {
      warnings.push(`Stock not updated for a line with quantity ${qty} (inventory tracks whole units).`);
      continue;
    }
    try {
      await addMovement({ product: l.inventoryProductId, quantity: qty, movement_type: 'OUT', notes: `Invoice #${invoiceId}` });
    } catch (e) {
      warnings.push(`Could not deduct stock: ${errorMessage(e)}`);
    }
  }
  return warnings;
}

/** Values of an existing line as {columnId: value}, for pre-filling the edit sheet. */
export const lineValues = (line: LineItem): Record<number, string> =>
  Object.fromEntries(line.product_properties.map((p) => [p.new_product_in_frontend.id, p.value ?? '']));

/**
 * Change the values of a line that is already on an invoice. Existing column values are updated in place;
 * a column the line never had a value for (added to the company's config later) gets a new property
 * attached. The line's amounts are recomputed from the new values.
 */
export async function updateLineItem(line: LineItem, values: Record<number, string>, columns: Column[]) {
  const calc = calculateLine(columns.map((c) => ({ column: c, value: values[c.id] ?? '' })), columns);
  const amounts = { gst_amount: calc.gst_amount.toFixed(2), total_amount: calc.total_amount.toFixed(2) };

  const attach: number[] = [];
  for (const c of columns) {
    const existing = line.product_properties.find((p) => p.new_product_in_frontend.id === c.id);
    const value = values[c.id] ?? '';
    if (existing) {
      if ((existing.value ?? '') !== value) await api.post(`product/properties/${existing.id}/update/`, { value });
    } else {
      const { data } = await api.post<{ id: number }>('product/properties/', { new_product_in_frontend: c.id, value });
      attach.push(data.id);
    }
  }
  await api.post(`product/${line.id}/update/`, { ...(attach.length ? { product_properties: attach.join(',') } : {}), ...amounts });
}

export const removeLineItem = (productId: number) => api.delete(`product/${productId}/update/`);

export const deleteInvoice = (id: number) => api.delete('invoice/', { params: { id } });

/**
 * Create an invoice with its lines. If any step fails after the invoice row
 * exists, the half-built invoice is deleted so the user doesn't end up with a
 * number-consuming empty invoice they never saw.
 */
const partyBody = (type: InvoiceType, party: number) => (type === 'purchase' ? { vendor: party } : { receiver: party });

const OPTIONAL_HEADER_FIELDS = ['payment_status', 'payment_method', 'due_date', 'place_of_supply', 'customer_notes', 'terms'] as const;

/**
 * The body for creating an invoice. Anything left blank is omitted rather than sent empty: a missing invoice
 * number is auto-generated, and a missing optional field gets the company's default, both by the server.
 */
export function invoiceBody(input: InvoiceInput, type: InvoiceType, totals: { total: number; gst: number }) {
  const { party, ...rest } = input;
  const body: Record<string, unknown> = {
    ...rest,
    ...partyBody(type, party),
    invoice_type: type,
    total_final_amount: totals.total.toFixed(2),
    gst_final_amount: totals.gst.toFixed(2),
  };
  if (!input.invoice_number?.trim()) delete body.invoice_number;
  for (const key of OPTIONAL_HEADER_FIELDS) {
    const v = body[key];
    if (v === undefined || v === null || (typeof v === 'string' && !v.trim())) delete body[key];
  }
  return body;
}

export async function createInvoice(input: InvoiceInput, lines: NewLine[], columns: Column[], type: InvoiceType = 'sales') {
  const body = invoiceBody(input, type, totalsFor(lines, columns));

  const { data: inv } = await api.post<Invoice>('invoice/', body);
  try {
    for (const l of lines) await addLineItem(inv.id, l, columns);
  } catch (e) {
    await deleteInvoice(inv.id).catch(() => {});
    throw e;
  }
  const warnings = await deductStock(inv.id, lines, columns);
  return { invoice: inv, warnings };
}

export async function updateInvoice(
  id: number,
  patch: Partial<Omit<InvoiceInput, 'party'>> & { party?: number; total_final_amount?: string; gst_final_amount?: string },
  type: InvoiceType = 'sales',
) {
  return (await api.post<Invoice>(`invoice/${id}/update/`, invoicePatchBody(patch, type))).data;
}

/**
 * The body for editing an invoice. Clearing the due date sends null: the API is JSON here, and a date field
 * accepts null but rejects an empty string.
 */
export function invoicePatchBody(
  patch: Partial<Omit<InvoiceInput, 'party'>> & { party?: number; total_final_amount?: string; gst_final_amount?: string },
  type: InvoiceType,
) {
  const { party, ...rest } = patch;
  const body: Record<string, unknown> = { ...rest, ...(party != null ? partyBody(type, party) : {}) };
  if (patch.invoice_number !== undefined && !patch.invoice_number.trim()) body.invoice_number = '';
  if (patch.due_date !== undefined && !patch.due_date) body.due_date = null;
  return body;
}

/** Recompute and store the invoice totals from its current lines. */
export async function syncTotals(id: number) {
  const inv = await getInvoice(id);
  const total = inv.products.reduce((s, p) => s + Number(p.total_amount || 0), 0);
  const gst = inv.products.reduce((s, p) => s + Number(p.gst_amount || 0), 0);
  return updateInvoice(id, { total_final_amount: total.toFixed(2), gst_final_amount: gst.toFixed(2) });
}

/** Download the invoice PDF to the cache dir and return its local uri. */
export async function downloadPdf(id: number, templateId?: number) {
  const token = await getToken();
  const root = (process.env.EXPO_PUBLIC_API_URL ?? '').replace(/\/+$/, '');
  const url = `${root}/api/pdf/?id=${id}${templateId ? `&template_id=${templateId}` : ''}`;
  const target = `${FileSystem.cacheDirectory}invoice-${id}.pdf`;
  const res = await FileSystem.downloadAsync(url, target, {
    headers: { Authorization: `Bearer ${token}`, 'X-Client': 'mobile' },
  });
  const type = Object.entries(res.headers ?? {}).find(([k]) => k.toLowerCase() === 'content-type')?.[1] ?? '';
  // the server answers some render failures with 200 and a junk "error.pdf"; only trust a real PDF
  if (res.status !== 200 || !String(type).includes('pdf')) {
    throw new Error(res.status === 404 ? 'No invoice template is set up for your company.' : 'Could not generate the PDF.');
  }
  return res.uri;
}

export const shareOnWhatsapp = (invoice: number) => api.post('share_by_whatsapp/', { invoice });

