import api from './api';
import type { Paged } from './invoices';

export type PartyKind = 'customer' | 'vendor';

export type Party = {
  id: number;
  name: string;
  address: string;
  gst_number: string;
  phone_number: string | null;
  state: string;
  state_code: number | null;
  // present only on plans with customer stats
  invoice_count?: number;
  total_billed?: string;
  last_invoice_date?: string | null;
};

export type PartyInput = Pick<Party, 'name' | 'address' | 'gst_number' | 'state'> & {
  phone_number: string;
  state_code: string;
};

const path = (k: PartyKind) => (k === 'customer' ? 'companies/' : 'vendors/');

export const PERMISSION: Record<PartyKind, string> = { customer: 'customer.manage', vendor: 'vendor.manage' };
export const LABEL: Record<PartyKind, string> = { customer: 'Customer', vendor: 'Vendor' };

export async function listParties(kind: PartyKind, page: number, search: string) {
  const { data } = await api.get<Paged<Party>>(path(kind), {
    params: { page, page_size: 20, ...(search ? { search } : {}) },
  });
  return data;
}

export async function getParty(kind: PartyKind, id: number) {
  const { data } = await api.get<Paged<Party>>(path(kind), { params: { page_size: 1, ...(kind === 'customer' ? { id } : {}) } });
  const hit = kind === 'customer' ? data.results[0] : undefined;
  if (hit) return hit;
  // vendors can't be filtered by id server-side; walk the (small) list
  for (let page = 1; ; page++) {
    const p = await listParties(kind, page, '');
    const found = p.results.find((r) => r.id === id);
    if (found) return found;
    if (!p.next) throw new Error(`${LABEL[kind]} not found`);
  }
}

function body(input: PartyInput) {
  return {
    name: input.name.trim(),
    address: input.address.trim(),
    gst_number: input.gst_number.trim().toUpperCase(),
    state: input.state.trim(),
    state_code: input.state_code.trim() ? Number(input.state_code) : null,
    phone_number: input.phone_number.trim() || null,
  };
}

export async function saveParty(kind: PartyKind, input: PartyInput, id?: number) {
  const url = id ? `${path(kind)}${id}/` : path(kind);
  return (await api.post<Party>(url, body(input))).data;
}

export const deleteParty = (kind: PartyKind, id: number) => api.delete(`${path(kind)}${id}/`);
