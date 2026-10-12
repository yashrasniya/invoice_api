import * as FileSystem from 'expo-file-system/legacy';
import api from './api';
import { getToken } from './token-storage';

export type MyTemplate = {
  id: number; template_name: string; pdf_template: string | null; is_html: boolean;
  is_default: boolean; is_global: boolean; global_category: string; is_published: boolean;
};
export type GalleryTemplate = {
  id: number; template_name: string; pdf_template: string | null; preview_url: string | null;
  global_category: string; is_html: boolean; description: string | null; page_size: string | null;
};

const rows = <T,>(d: T[] | { results: T[] }): T[] => (Array.isArray(d) ? d : d.results);

export async function fetchMyTemplates() {
  const { data } = await api.get<MyTemplate[] | { results: MyTemplate[] }>('yaml/list/', { params: { only_my: 1 } });
  return rows(data);
}
export async function fetchGallery(category?: string) {
  const { data } = await api.get<GalleryTemplate[] | { results: GalleryTemplate[] }>('yaml/gallery/', {
    params: category ? { category } : {},
  });
  return rows(data);
}
export const setDefaultTemplate = (id: number) => api.post(`yaml/${id}/set-default/`);
export const cloneTemplate = async (id: number) => (await api.post<{ id: number; template_name: string }>(`yaml/gallery/${id}/clone/`)).data;

/** Sample-data PDF of a gallery template, downloaded with the user's token; returns the local uri. */
export async function downloadPreview(id: number) {
  const token = await getToken();
  const root = (process.env.EXPO_PUBLIC_API_URL ?? '').replace(/\/+$/, '');
  const target = `${FileSystem.cacheDirectory}template-preview-${id}.pdf`;
  const res = await FileSystem.downloadAsync(`${root}/api/yaml/gallery/${id}/preview/`, target, {
    headers: { Authorization: `Bearer ${token}`, 'X-Client': 'mobile' },
  });
  const type = Object.entries(res.headers ?? {}).find(([k]) => k.toLowerCase() === 'content-type')?.[1] ?? '';
  if (res.status !== 200 || !String(type).includes('pdf')) {
    throw new Error(res.status === 404 ? 'This template has no live preview.' : 'Could not render the preview.');
  }
  return res.uri;
}

// ── invoice numbering ───────────────────────────────────────────────────────
export type Numbering = {
  enabled: boolean; template: string; reset_period: string; next_number: number;
  max_length: number; gst_recommended_max_length: number;
  reset_options: { value: string; label: string }[];
  tokens: { token: string; label: string; example: string }[];
  default_template: string;
  valid?: boolean; preview?: string; length?: number; gst_warning?: boolean; error?: string;
};
export type NumberingPreview = { valid: boolean; preview?: string; length?: number; gst_warning?: boolean; error?: string };

export const fetchNumbering = async () => (await api.get<Numbering>('invoice-numbering/')).data;
export const previewNumbering = async (template: string, reset_period: string, next_number: number) =>
  (await api.get<NumberingPreview>('invoice-numbering/', { params: { template, reset_period, next_number } })).data;
export const saveNumbering = async (input: { enabled: boolean; template: string; reset_period: string; next_number: number }) =>
  (await api.post<Numbering>('invoice-numbering/', input)).data;
