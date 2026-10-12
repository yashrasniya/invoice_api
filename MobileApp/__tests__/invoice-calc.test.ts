import { calculateLine, compactInr, money } from '@/lib/invoice-calc';
import type { Column } from '@/services/invoices';

const col = (id: number, title: string, o: Partial<Column> = {}): Column => ({
  id, input_title: title, is_show: true, is_calculable: false, formula: '', on_with_out_gst_amount: false,
  presets: null, default_value: null, ...o,
});

// the typical company config: Name, Quantity × Rate, GST
const NAME = col(1, 'Name of Product');
const QTY = col(2, 'Quantity', { is_calculable: true });
const RATE = col(3, 'Rate', { is_calculable: true });
const GST = col(4, 'GST', { is_calculable: true });
const COLS = [NAME, QTY, RATE, GST];

const line = (cols: Column[], values: Record<number, string>) =>
  calculateLine(cols.map((c) => ({ column: c, value: values[c.id] ?? '' })), cols);

describe('calculateLine (port of the web calculateProductTotals)', () => {
  it('multiplies quantity by rate and adds GST on top', () => {
    const r = line(COLS, { 1: 'Widget', 2: '2', 3: '100', 4: '18' });
    expect(r.gst_amount).toBeCloseTo(36);
    expect(r.total_amount).toBeCloseTo(236);
  });

  it('GST column is never used as a multiplier', () => {
    expect(line(COLS, { 2: '1', 3: '100', 4: '28' }).total_amount).toBeCloseTo(128);
  });

  it('blank values do not zero the total', () => {
    expect(line(COLS, { 2: '3', 3: '50' }).total_amount).toBeCloseTo(150);   // no GST entered
  });

  it('%- applies a discount to the running total before GST', () => {
    const DISC = col(5, 'Discount', { is_calculable: true, formula: '%-' });
    const r = line([...COLS, DISC], { 2: '1', 3: '200', 4: '10', 5: '10' });
    expect(r.total_amount).toBeCloseTo(198);      // 200 − 10% = 180, +10% GST = 198
    expect(r.gst_amount).toBeCloseTo(18);
  });

  it('formula columns marked "without GST" stay outside the GST base', () => {
    const FREIGHT = col(5, 'Freight', { is_calculable: true, formula: '+', on_with_out_gst_amount: true });
    const r = line([...COLS, FREIGHT], { 2: '1', 3: '100', 4: '18', 5: '50' });
    expect(r.gst_amount).toBeCloseTo(18);          // GST on 100, not on 150
    expect(r.total_amount).toBeCloseTo(168);
  });

  it('division by zero is guarded', () => {
    const DIV = col(5, 'Per', { is_calculable: true, formula: '/' });
    const r = line([...COLS, DIV], { 2: '1', 3: '100', 5: '0' });
    expect(Number.isFinite(r.total_amount)).toBe(true);
  });

  it('a blank line is worth nothing, not a phantom ₹1', () => {
    expect(line(COLS, {})).toEqual({ total_amount: 0, gst_amount: 0 });
    expect(line(COLS, { 1: 'Just a name' }).total_amount).toBe(0);
    expect(line(COLS, { 4: '18' }).total_amount).toBe(0);      // GST alone has nothing to apply to
  });

  it('never returns NaN for garbage input', () => {
    const r = line(COLS, { 2: 'abc', 3: '--', 4: 'x' });
    expect(Number.isFinite(r.total_amount)).toBe(true);
    expect(Number.isFinite(r.gst_amount)).toBe(true);
  });
});

describe('formatting', () => {
  it('formats rupees with Indian grouping and 2 decimals', () => {
    expect(money(1234567.5)).toBe('₹12,34,567.50');
    expect(money(null)).toBe('₹0.00');
    expect(money('99')).toBe('₹99.00');
  });
  it('compacts for charts', () => {
    expect(compactInr(950)).toBe('₹950');
    expect(compactInr(12_500)).toBe('₹12.5K');
    expect(compactInr(340_000)).toBe('₹3.4L');
    expect(compactInr(25_000_000)).toBe('₹2.5Cr');
    expect(compactInr(-1500)).toBe('-₹1.5K');
  });
});
