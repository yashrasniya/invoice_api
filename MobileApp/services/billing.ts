import api from './api';

export type PlanFeature = { code: string; name: string; limits: Record<string, number> };
export type Plan = {
  id: number; code: string; name: string; description: string;
  monthly_price: string; yearly_price: string; features: PlanFeature[]; is_current: boolean;
};
export type BillingStatus = {
  entitlement: {
    plan_code: string | null; plan_name: string | null; status: string | null;
    start_date: string | null; end_date: string | null; auto_renew: boolean; is_working: boolean;
  } | null;
  billing_subscription: {
    status: string; period: string; current_end: string | null; charge_at: string | null;
    cancel_at_cycle_end: boolean; paid_count: number; total_count: number | null;
  } | null;
  scheduled_change: { to_plan_name: string; effective_date: string; period: string } | null;
};
export type Payment = {
  id: number; amount: string; currency: string; status: string; method: string | null;
  description: string | null; plan_code: string | null; paid_at: string | null; created_at: string;
};

export const fetchBilling = async () => (await api.get<BillingStatus>('billing/subscription/')).data;
export const fetchPlans = async () => (await api.get<{ plans: Plan[]; currency: string }>('billing/plans/')).data.plans;
export async function fetchPayments() {
  const { data } = await api.get<Payment[] | { results: Payment[] }>('billing/payments/');
  return Array.isArray(data) ? data : data.results;
}
