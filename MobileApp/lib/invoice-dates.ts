/** Date helpers for the invoice form. Dates travel as `YYYY-MM-DD` strings, never as timestamps. */

export const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export const parseYmd = (s: string) => {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
};

const YMD = /^(\d{4})-(\d{2})-(\d{2})/;
const utc = (s: string) => {
  const m = YMD.exec(s);
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
};

/** `s` plus `days`, as `YYYY-MM-DD`. Calendar arithmetic, so a daylight-saving change can't shift the result a day. */
export function addDaysYmd(s: string, days: number) {
  const base = utc(s);
  return base === null ? s : new Date(base + days * 86_400_000).toISOString().slice(0, 10);
}

/** Whole days from one date to another, or null if either isn't a valid date. */
export function daysBetweenYmd(from: string, to: string) {
  const a = utc(from);
  const b = utc(to);
  return a === null || b === null ? null : Math.round((b - a) / 86_400_000);
}

/** The "Net N" shortcuts; 0 is "due on receipt". Matches the web editor and the server's default-terms list. */
export const PAYMENT_TERMS: { days: number; label: string }[] = [
  { days: 0, label: 'Due on receipt' },
  { days: 7, label: 'Net 7' },
  { days: 15, label: 'Net 15' },
  { days: 30, label: 'Net 30' },
  { days: 45, label: 'Net 45' },
  { days: 60, label: 'Net 60' },
];

/** Days between the invoice date and the due date, or null when there is no due date. */
export const termDays = (date: string, due: string | null) => (due ? daysBetweenYmd(date, due) : null);

/**
 * Moving the invoice date carries the due date with it, so a "Net 15" invoice stays Net 15 and can never end
 * up due before it is issued. With no due date there is nothing to carry.
 */
export function dueAfterDateChange(oldDate: string, newDate: string, due: string | null) {
  if (!due) return null;
  const term = daysBetweenYmd(oldDate, due);
  return addDaysYmd(newDate, term === null ? 0 : Math.max(term, 0));
}
