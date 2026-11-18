import * as FileSystem from 'expo-file-system/legacy';
import api from './api';

/** E-way bills, Phase A: details are saved here, the JSON is uploaded on the portal by the user. */
export type EwayIssue = { level: 'error' | 'warning'; code: string; message: string };
export type EwayVerdict = {
  needed: boolean;
  code: 'over_limit' | 'under_limit' | 'services' | 'purchase';
  reason: string; consignment_value: number; limit: number | null;
};
export type TransportMode = 1 | 2 | 3 | 4;
export type EwayBill = {
  sub_supply_type: 1 | 3 | 9;
  doc_type: 'INV' | 'BIL';
  ship_to_name: string; ship_to_address: string; ship_to_place: string;
  ship_to_state_code: number | null; ship_to_pincode: string;
  distance_km: number;
  transport_mode: TransportMode;
  vehicle_number: string; vehicle_type: 'R' | 'O';
  transporter_id: string; transporter_name: string;
  transport_doc_number: string; transport_doc_date: string | null;
  ewb_number: string; ewb_date: string | null; valid_until: string | null;
  status: 'draft' | 'generated' | 'cancelled';
  source: 'manual' | 'api';
  updated_at?: string;
};
export type EwayBillInput = Partial<Omit<EwayBill, 'source' | 'updated_at'>>;
export type EwayDetail = {
  invoice: { id: number; invoice_number: string | null; date: string | null; customer: string | null; total: number };
  verdict: EwayVerdict;
  saved: boolean;
  eway_bill: EwayBill;
  ready: boolean;
  issues: EwayIssue[];
  validity_if_generated_now: string | null;
};

export const MODE_LABEL: Record<TransportMode, string> = { 1: 'Road', 2: 'Rail', 3: 'Air', 4: 'Ship' };
export const SUB_SUPPLY_LABEL: Record<EwayBill['sub_supply_type'], string> = { 1: 'Supply', 3: 'Export', 9: 'SKD/CKD/Lots' };

export const fetchEway = async (invoiceId: number) =>
  (await api.get<EwayDetail>(`eway/${invoiceId}/`)).data;

export const saveEway = async (invoiceId: number, input: EwayBillInput) =>
  (await api.put<EwayDetail>(`eway/${invoiceId}/`, input)).data;

/** The portal's bulk-upload JSON for these invoices, written to the cache dir; returns the local uri. */
export async function downloadEwayJson(invoiceIds: number[], name: string) {
  const { data } = await api.get<string>('eway/json/', {
    params: { ids: invoiceIds.join(','), download: 1 }, responseType: 'text', transformResponse: (d) => d,
  });
  const uri = `${FileSystem.cacheDirectory}EWB_${name.replace(/[^A-Za-z0-9_-]+/g, '_') || 'bulk'}.json`;
  await FileSystem.writeAsStringAsync(uri, data);
  return uri;
}

export type EwayPending = {
  days: number; count: number;
  invoices: { invoice_id: number; invoice_number: string | null; date: string | null; customer: string | null; consignment_value: number }[];
};
export const fetchEwayPending = async (days = 30) =>
  (await api.get<EwayPending>('eway/pending/', { params: { days } })).data;

/** "17 Nov 2026, 23:59" in the device's locale, for the ISO datetimes the API returns. */
export function formatEwayTime(iso: string | null) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
