import type { Column } from '@/services/invoices';

export type PropValue = { column: Column; value: string };

/**
 * Line-item maths, ported 1:1 from the web app's calculateProductTotals so an
 * invoice built on the phone totals exactly like one built in the browser.
 * Columns are company-configured: each can multiply, add, subtract, divide or
 * apply a percentage to the running total, optionally outside the GST base.
 */
export function calculateLine(props: PropValue[], columns: Column[]) {
  // The running total starts at 1 so columns can multiply into it. With nothing to multiply
  // (no quantity/rate typed yet) that would leave a phantom ₹1 line — a blank line is worth 0.
  const hasAmountInput = props.some(
    (p) => p.column.is_calculable && p.column.input_title !== 'GST' && (p.value ?? '').toString().trim() !== '',
  );
  if (!hasAmountInput) return { total_amount: 0, gst_amount: 0 };

  let total = 1;
  let extra = 0;

  const apply = ({ column: c, value }: PropValue) => {
    if (!c.is_calculable) return;
    const val = parseFloat(value) || 0;
    if (c.formula) {
      switch (c.formula) {
        case '+': c.on_with_out_gst_amount ? (extra += val) : (total += val); break;
        case '-': c.on_with_out_gst_amount ? (extra -= val) : (total -= val); break;
        case '/': total /= val || 1; break;
        case '%+': { const x = (val / 100) * total; c.on_with_out_gst_amount ? (extra += x) : (total += x); break; }
        case '%-': { const x = (val / 100) * total; c.on_with_out_gst_amount ? (extra -= x) : (total -= x); break; }
      }
    } else if (value && c.input_title !== 'GST') {
      total *= parseFloat(value);
    }
  };

  // plain multipliers first, then formula columns
  [...props]
    .sort((a, b) => Number(!!a.column.formula) - Number(!!b.column.formula))
    .forEach(apply);

  let gst = 0;
  const gstCol = columns.find((c) => c.input_title === 'GST');
  if (props.length > 0 && gstCol) {
    const raw = props.find((p) => p.column.id === gstCol.id)?.value;
    gst = raw ? total * (parseFloat(raw) / 100) : 0;
  }
  const n = (x: number) => (Number.isFinite(x) ? x : 0);
  return { total_amount: n(total + gst + extra), gst_amount: n(gst) };
}

export const money = (n: number | string | null | undefined) =>
  `₹${Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** ₹1.2K / ₹3.4L / ₹1.1Cr — for chart axes and tight cards. */
export function compactInr(n: number) {
  const v = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (v >= 1e7) return `${sign}₹${(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `${sign}₹${(v / 1e5).toFixed(1)}L`;
  if (v >= 1e3) return `${sign}₹${(v / 1e3).toFixed(1)}K`;
  return `${sign}₹${Math.round(v)}`;
}
