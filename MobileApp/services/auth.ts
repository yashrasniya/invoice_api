import api from './api';

export type User = {
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  name: string;
  gender?: string | null;
  mobile_number?: string | null;
  profile?: string | null;
  dob?: string | null;
  is_company_varified?: boolean;
  is_company_admin?: boolean;
};

export type Access = {
  company_id: number | null;
  company_name: string | null;
  permissions: string[];
  features: string[];
  subscription: Record<string, any> | null;
  is_tenant_admin: boolean;
  is_product_owner: boolean;
  line_item_images_enabled: boolean;
};

export type RegisterInput = {
  username: string;
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  mobile_number: string;
};

export async function login(username: string, password: string) {
  const { data } = await api.post<User & { access?: string }>('login/', { username, password });
  if (!data.access) throw new Error('Server did not return a session token. Is the backend up to date?');
  return { token: data.access, user: data as User };
}

/** Exchange a Google ID token for our own session (creates the account on first sign-in). */
export async function googleLogin(credential: string) {
  const { data } = await api.post<User & { access?: string; created?: boolean }>('google-login/', { credential });
  if (!data.access) throw new Error('Server did not return a session token. Is the backend up to date?');
  return { token: data.access, user: data as User, created: !!data.created };
}

export const register = (input: RegisterInput) => api.post('register/', input);

export const fetchProfile = async () => (await api.get<User>('profile/')).data;

export const updateProfile = async (patch: Partial<User>) => (await api.post<User>('profile/', patch)).data;

export const fetchAccess = async () => (await api.get<Access>('authz/me/')).data;

export const logoutRequest = () => api.get('log_out/');

export const fetchInvite = async (token: string) =>
  (await api.get<{ valid: boolean; email: string; company_name: string; existing_account: boolean }>(`invites/${token}/`)).data;

export async function acceptInvite(
  token: string,
  payload: { username?: string; password?: string; first_name?: string; last_name?: string },
) {
  const { data } = await api.post<User & { access?: string }>(`invites/${token}/accept/`, payload);
  if (!data.access) throw new Error('Server did not return a session token.');
  return { token: data.access, user: data as User };
}

export type DashboardRange = 'this_month' | 'last_month' | 'last_30' | 'this_fy';
export const DASHBOARD_RANGES: { value: DashboardRange; label: string }[] = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_30', label: 'Last 30 days' },
  { value: 'this_fy', label: 'This FY' },
];

export type DashboardStats = {
  name: string;
  range_label: string;
  month_total_final_amount: number;
  month_gst_final_amount: number;
  prv_total_final_amount: number;
  percentage_change: number | null;
  percentage_gst_amount: number | null;
  invoices_this_month_count: number;
  receivable_amount: number;
  receivable_count: number;
  overdue_amount: number;
  overdue_count: number;
  has_any_invoice: boolean;
};

/** The KPI header: totals for the chosen range (cheap, shows first). */
export const fetchDashboard = async (range: DashboardRange = 'this_month') =>
  (await api.get<DashboardStats>('user_info/', { params: { range } })).data;

/** The charts and lists below the KPIs. Every section is already filtered by the user's permissions server-side. */
export type DashboardWidgets = {
  trend: { label: string; month: string; total: number; gst: number; count: number }[];
  recent_invoices: { id: number; invoice_number: string; customer: string; date: string | null; total: number; payment_status: string }[];
  top_customers: { id: number | null; name: string; total: number; count: number }[];
  payment_methods: { method: string; total: number; count: number }[];
  low_stock: { id: number; name: string; sku: string; current_stock: number; reorder_level: number }[];
  gst_due: { form: string; due_date: string; period: string; days_left: number }[];
};
export const fetchDashboardWidgets = async (range: DashboardRange = 'this_month') =>
  (await api.get<DashboardWidgets>('dashboard/', { params: { range } })).data;
