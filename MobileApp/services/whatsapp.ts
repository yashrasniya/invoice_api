import api from './api';

export type WaMode = 'platform' | 'own';
export type WaModeInfo = {
  mode: WaMode;
  default_invoice_template: { id: number; template_name: string } | null;
  options: Record<WaMode, { available: boolean; in_plan: boolean; configured: boolean; sends_per_day: number | null }>;
};
export type WaConfig = { status: string; business_account_id?: string; phone_number_id?: string };
export type WaTemplate = { id: number; template_name: string; category: string; status: string; meta_template_id: string; created_at: string };

export const fetchWaMode = async () => (await api.get<WaModeInfo>('whatsapp/mode/')).data;

export const updateWaMode = (patch: { mode?: WaMode; default_invoice_template?: number | null }) =>
  api.post('whatsapp/mode/', patch);

/** The own-number integration. The API answers 404 when none is set up, which is a normal state, not an error. */
export async function fetchWaConfig(): Promise<WaConfig> {
  try {
    return (await api.get<WaConfig>('whatsapp/config/')).data;
  } catch (e: any) {
    if (e?.response?.status === 404) return { status: 'not_configured' };
    throw e;
  }
}

export const fetchWaTemplates = async () => (await api.get<WaTemplate[]>('whatsapp/template/')).data;
export const syncWaTemplates = async () => (await api.post<{ added: number; updated: number }>('whatsapp/template/sync/')).data;
export const sendWaTest = (recipient_number: string, template_name: string) =>
  api.post('whatsapp/send-test/', { recipient_number, template_name });
