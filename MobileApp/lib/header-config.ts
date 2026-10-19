/**
 * Which optional invoice header fields a company shows, and the defaults a new invoice starts with.
 * The company sets this in the web app (UI Config → Invoice Fields); the phone only reads it.
 *
 * Fails open: if the settings can't be read, every field shows and nothing is defaulted, which is how the
 * app behaved before this existed. Defaults for fields the form leaves out are applied by the server when
 * an invoice is created.
 */
export type HeaderKey = 'place_of_supply' | 'payment_terms' | 'payment_status' | 'payment_method' | 'customer_notes' | 'terms';

export const HEADER_KEYS: HeaderKey[] = ['place_of_supply', 'payment_terms', 'payment_status', 'payment_method', 'customer_notes', 'terms'];

export type HeaderEntry = { visible: boolean; use_default: boolean; default: string | number | null };
export type HeaderConfig = Record<HeaderKey, HeaderEntry>;

type RawEntry = Partial<HeaderEntry> | null | undefined;

export function resolveHeader(raw?: Record<string, RawEntry> | null): HeaderConfig {
  const out = {} as HeaderConfig;
  for (const key of HEADER_KEYS) {
    const e = raw && typeof raw === 'object' ? raw[key] : undefined;
    out[key] = {
      visible: e?.visible ?? true,
      use_default: e?.use_default ?? false,
      default: e?.default ?? null,
    };
  }
  return out;
}

export const isVisible = (cfg: HeaderConfig, key: HeaderKey) => cfg[key].visible;

/** The default for a field, only when the company turned it on and gave it a value. */
export function defaultOf<T extends string | number>(cfg: HeaderConfig, key: HeaderKey): T | undefined {
  const e = cfg[key];
  if (!e.use_default || e.default === null || e.default === '') return undefined;
  return e.default as T;
}
