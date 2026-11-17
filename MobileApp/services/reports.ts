import * as FileSystem from 'expo-file-system/legacy';
import api from './api';
import type { InvoiceType } from './invoices';

export type DateRange = { start_date: string; end_date: string };

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export type RangePreset = 'last_7' | 'last_30' | 'this_month' | 'last_month' | 'this_fy';
export const RANGE_LABEL: Record<RangePreset, string> = {
  last_7: 'Last 7 days', last_30: 'Last 30 days', this_month: 'This month', last_month: 'Last month', this_fy: 'This FY',
};

/** Date range for a preset. The financial year runs 1 Apr – 31 Mar. */
export function rangeFor(preset: RangePreset, now = new Date()): DateRange {
  const y = now.getFullYear();
  const m = now.getMonth();
  switch (preset) {
    case 'last_7': return { start_date: ymd(new Date(y, m, now.getDate() - 6)), end_date: ymd(now) };
    case 'last_30': return { start_date: ymd(new Date(y, m, now.getDate() - 29)), end_date: ymd(now) };
    case 'this_month': return { start_date: ymd(new Date(y, m, 1)), end_date: ymd(now) };
    case 'last_month': return { start_date: ymd(new Date(y, m - 1, 1)), end_date: ymd(new Date(y, m, 0)) };
    case 'this_fy': {
      const fyStart = m >= 3 ? y : y - 1;
      return { start_date: ymd(new Date(fyStart, 3, 1)), end_date: ymd(now) };
    }
  }
}

// ── sales report ────────────────────────────────────────────────────────────
export type SalesReport = {
  summary: {
    total_sales: number; total_invoices: number; paid_amount: number; unpaid_amount: number; overdue_amount: number;
    average_invoice_value: number; gst_collected: number; credit_notes_issued: number; credit_notes_amount: number;
    top_customer: string; highest_sale_day: string; sales_growth_pct: number;
  };
  charts: {
    sales_trend: { date: string; sales: number }[];
    payment_status_distribution: { name: string; value: number }[];
    top_customers: { name: string; sales: number }[];
    sales_by_state: { state: string; sales: number }[];
    gst_trend: { date: string; gst: number }[];
    payment_method_distribution: { name: string; value: number }[];
  };
  kpis: { repeat_customer_pct: number; new_customers: number };
};
export const fetchSalesReport = async (r: DateRange) => (await api.get<SalesReport>('sales-report/', { params: r })).data;

// ── cash flow ───────────────────────────────────────────────────────────────
export type CashFlowPoint = { date: string; inflow: number; outflow: number; net: number };
export type Interval = 'daily' | 'weekly' | 'monthly';
export const fetchCashFlow = async (r: DateRange, interval: Interval) =>
  (await api.get<CashFlowPoint[]>('cash-flow/', { params: { ...r, interval } })).data;

// ── GST summary ─────────────────────────────────────────────────────────────
export type GstPeriod = 'this_month' | 'last_month' | 'this_quarter' | 'last_quarter' | 'this_fy';
export const GST_PERIOD_LABEL: Record<GstPeriod, string> = {
  this_month: 'This month', last_month: 'Last month', this_quarter: 'This quarter', last_quarter: 'Last quarter', this_fy: 'This FY',
};
export type GstSummary = {
  period_label: string; start_date: string; end_date: string;
  total_sales_taxable: number; total_purchases_taxable: number;
  output_gst: number; input_gst: number; net_gst_payable: number;
  sales_invoice_count: number; purchase_invoice_count: number;
  tax_split: { cgst: number; sgst: number; igst: number; unclassified: number; unclassified_invoices: number };
  credit_note_value: number; credit_note_count: number; debit_note_value: number; debit_note_count: number;
  /** Tax moved by notes that carry a GST amount; already included in net_gst_payable. */
  output_tax_adjustment: number; input_tax_adjustment: number;
  notes_without_gst: number; notes_reduce_liability: boolean;
  data_quality: GstIssue[];
};
export type GstIssue = { level: 'error' | 'warning'; code: string; title: string; detail: string; fix: string };
export const fetchGstSummary = async (period: GstPeriod) =>
  (await api.get<GstSummary>('gst-summary/', { params: { period } })).data;

// ── GSTR-1 ──────────────────────────────────────────────────────────────────
export type Gstr1Period = 'last_month' | 'this_month' | 'last_quarter' | 'this_quarter';
export const GSTR1_PERIOD_LABEL: Record<Gstr1Period, string> = {
  last_month: 'Last month', this_month: 'This month', last_quarter: 'Last quarter', this_quarter: 'This quarter',
};
export type Gstr1Issue = {
  level: 'error' | 'warning'; code: string; message: string;
  ref: { kind: 'invoice' | 'note'; id: number; number: string; date: string } | null;
};
export type Gstr1Summary = {
  period_label: string; start_date: string; end_date: string; gstin: string; fp: string;
  tables: { table: string; label: string; count: number; taxable: number; tax: number }[];
  b2b_customers: number; hsn_rows: number; total_taxable: number; total_tax: number;
  documents: { num: number; from: string; to: string; totnum: number; cancel: number; net_issue: number }[];
  issues: Gstr1Issue[]; error_count: number; warning_count: number; ready_to_file: boolean;
};
export const fetchGstr1 = async (period: Gstr1Period) =>
  (await api.get<Gstr1Summary>('gstr1/', { params: { period } })).data;

/** The portal / offline-tool JSON, saved to the cache dir. The server refuses (409) while errors remain. */
export async function downloadGstr1(period: Gstr1Period, gstin: string, fp: string) {
  const { data } = await api.get<string>('gstr1/', {
    params: { period, download: 1 }, responseType: 'text', transformResponse: (d) => d,
  });
  const uri = `${FileSystem.cacheDirectory}GSTR1_${gstin || 'NA'}_${fp}.json`;
  await FileSystem.writeAsStringAsync(uri, data);
  return uri;
}

// ── ledger ──────────────────────────────────────────────────────────────────
export type LedgerPeriod = GstPeriod | 'all_time';
export type Ledger = {
  period_label: string; start_date: string; end_date: string;
  opening_balance: number; closing_balance: number;
  transactions: { date: string | null; vch_type: string; particulars?: string; vch_no?: string | null; invoice_id?: number | null; debit: number; credit: number; balance: number }[];
  party: { id: number; name: string; gst_number: string; phone_number: string; state: string };
  outstanding_total: number; outstanding_count: number;
  ageing: { label: string; amount: number; count: number }[];
  open_invoices: { id: number; invoice_number: string; date: string | null; billed: number; paid: number; due: number; age_days: number; payment_status: string }[];
  lifetime: { billed: number; gst: number; settled: number; largest_invoice: number };
};
export const fetchLedger = async (kind: 'customer' | 'vendor', id: number, period: LedgerPeriod) =>
  (await api.get<Ledger>(`ledger/${kind}/${id}/`, { params: { period } })).data;

// ── export ──────────────────────────────────────────────────────────────────
/** CSV of invoices in a range, written to the cache dir; returns the local uri. */
export async function exportInvoicesCsv(r: DateRange, type: InvoiceType) {
  const { data } = await api.post<string>(
    'bulk_export/',
    { type: 'CSV', date_from: r.start_date, date_to: r.end_date, invoice_type: type },
    { responseType: 'text', transformResponse: (d) => d },
  );
  const uri = `${FileSystem.cacheDirectory}${type}-invoices-${r.start_date}-to-${r.end_date}.csv`;
  await FileSystem.writeAsStringAsync(uri, data);
  return uri;
}
