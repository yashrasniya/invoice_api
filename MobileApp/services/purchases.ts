import api from './api';

export type PurchaseSummary = {
  total_purchases_amount: number;
  total_purchases_gst: number;
  this_month_purchases_amount: number;
  total_count: number;
  this_month_count: number;
};
export const fetchPurchaseSummary = async () => (await api.get<PurchaseSummary>('purchase-summary/')).data;

export type OcrState = 'completed' | 'processing' | 'failed';
export type OcrJob = {
  id: number;
  job_id: string | null;
  file_name: string;
  status: string | null;
  state: OcrState;
  created_at: string;
  extracted: {
    invoice_number: string | null; date: string | null; vendor_name: string | null;
    total_amount: number | string | null; gst_amount: number | string | null;
  };
};
export type OcrJobs = {
  usage: { this_month: number; monthly_limit: number | null; today: number; daily_limit: number; total: number };
  counts: { completed: number; failed: number; processing: number };
  jobs: OcrJob[];
};
export const fetchOcrJobs = async () => (await api.get<OcrJobs>('purchase/ocr-jobs/', { params: { limit: 50 } })).data;

/** Ask the pipeline for the job's latest status (the server stores it), then re-list. */
export const refreshOcrJob = (jobId: string) => api.get(`purchase/status/${jobId}/`);

export type BillFile = { uri: string; name: string; mimeType: string };

export async function uploadBill(file: BillFile) {
  const form = new FormData();
  // React Native's FormData accepts a { uri, name, type } descriptor in place of a Blob
  form.append('file', { uri: file.uri, name: file.name, type: file.mimeType } as unknown as Blob);
  form.append('invoice_type', 'purchase');
  const { data } = await api.post('purchase/upload/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000, // the server waits on the extraction service before answering
    transformRequest: (d) => d, // keep RN's FormData intact (axios would otherwise try to serialise it)
  });
  return data as { job_id?: string; status?: string };
}
