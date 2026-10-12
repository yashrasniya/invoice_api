import type { Column, LineItem, NewLine } from '@/services/invoices';

type Pair = { column: Column; value: string };

/** Pick a headline (the product name) and a one-line summary from a line's column values. */
function summarize(pairs: Pair[]) {
  const filled = pairs.filter((p) => (p.value ?? '').toString().trim() !== '');
  const head = filled.find((p) => /name|product|item|description/i.test(p.column.input_title)) ?? filled[0];
  const details = filled
    .filter((p) => p !== head && p.column.is_show)
    .map((p) => `${p.column.input_title}: ${p.value}`)
    .join(' · ');
  return { name: head?.value?.toString() || 'Item', details };
}

export const summarizeLine = (line: LineItem) =>
  summarize(line.product_properties.map((p) => ({ column: p.new_product_in_frontend, value: p.value ?? '' })));

export const summarizeNewLine = (line: NewLine, columns: Column[]) =>
  summarize(columns.map((c) => ({ column: c, value: line.values[c.id] ?? '' })));
