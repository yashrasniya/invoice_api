import axios, { AxiosError } from 'axios';
import { getToken } from './token-storage';

const root = (process.env.EXPO_PUBLIC_API_URL ?? '').replace(/\/+$/, '');

/** Media paths come back relative from login responses; make them loadable. */
export const mediaUrl = (u?: string | null) => (u && u.startsWith('/') ? `${root}${u}` : u || undefined);

export const WEB_URL = (process.env.EXPO_PUBLIC_WEB_URL ?? '').replace(/\/+$/, '');

const api = axios.create({
  baseURL: `${root}/api/`,
  headers: {
    'Content-Type': 'application/json',
    // tells the backend to return the bearer token in the login response body
    'X-Client': 'mobile',
  },
  timeout: 20000,
});

api.interceptors.request.use(async (config) => {
  const token = await getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Registered by the session store so this module doesn't import it (avoids a cycle).
type Handlers = {
  onUnauthorized?: () => void;
  onUpgradeRequired?: (message: string) => void;
};
const handlers: Handlers = {};
export const setApiHandlers = (h: Handlers) => Object.assign(handlers, h);

api.interceptors.response.use(
  (res) => res,
  (error: AxiosError<any>) => {
    const status = error.response?.status;
    const data = error.response?.data;
    const url = error.config?.url ?? '';
    // login/register legitimately return 401/400 for bad credentials — don't treat as session expiry
    const isAuthCall = /^(login|register|invites)\//.test(url);
    if (status === 401 && !isAuthCall) handlers.onUnauthorized?.();
    if (status === 403 && data?.code === 'upgrade_required') {
      handlers.onUpgradeRequired?.(data?.detail || data?.error || 'Upgrade your plan to use this feature.');
    }
    return Promise.reject(error);
  },
);

/** Flatten the backend's assorted error shapes ({error}, {detail}, DRF field errors) into one string. */
export function errorMessage(error: unknown, fallback = 'Something went wrong. Please try again.'): string {
  const e = error as AxiosError<any>;
  if (!e?.response) return e?.code === 'ECONNABORTED' || e?.message === 'Network Error'
    ? 'Cannot reach the server. Check your connection.' : fallback;
  const d = e.response.data;
  if (typeof d === 'string') return d.length < 200 ? d : fallback;
  if (d?.detail) return String(d.detail);
  if (d?.error) return String(d.error);
  if (Array.isArray(d)) return String(d[0]);
  if (d && typeof d === 'object') {
    const first = Object.entries(d).find(([, v]) => v);
    if (first) {
      const [field, v] = first;
      const msg = Array.isArray(v) ? v[0] : v;
      return field === 'non_field_errors' ? String(msg) : `${field}: ${msg}`;
    }
  }
  return fallback;
}

/** True for failures that mean "never reached the server" (offline, timeout), as opposed to "the server said no". */
export function isOfflineError(e: unknown) {
  const err = e as { response?: unknown; code?: string; message?: string };
  return !err?.response && (err?.code === 'ECONNABORTED' || err?.code === 'ERR_NETWORK' || err?.message === 'Network Error');
}

export default api;

/**
 * Per-field validation messages from a DRF 400 (`{ email: ['...'], password: ['...'] }`), first message per field.
 * Empty when the response isn't field-shaped, so callers fall back to errorMessage().
 */
export function fieldErrors(error: unknown): Record<string, string> {
  const d = (error as AxiosError<any>)?.response?.data;
  if (!d || typeof d !== 'object' || Array.isArray(d)) return {};
  const out: Record<string, string> = {};
  for (const [field, v] of Object.entries(d)) {
    if (field === 'code' || field === 'detail' || field === 'error') continue;
    const msg = Array.isArray(v) ? v[0] : v;
    if (typeof msg === 'string' && msg) out[field] = msg;
  }
  return out;
}

/** The machine-readable `code` the backend adds to some errors (e.g. 'email_exists'), if any. */
export const apiErrorCode = (error: unknown): string | undefined => {
  const code = (error as AxiosError<any>)?.response?.data?.code;
  return typeof code === 'string' ? code : undefined;
};
