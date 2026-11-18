import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { IssueSections, TaxLine, headsText } from '@/components/gst-return-ui';
import { Centered, EmptyState } from '@/components/ui/bits';
import { useThemedStyles, type Theme } from '@/hooks/use-theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { fetchGstr9 } from '@/services/reports';

/** Start year of the financial year containing `d` (Apr–Mar). */
const fyOf = (d: Date) => (d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1);
const fyLabel = (y: number) => `FY ${y}-${String(y + 1).slice(2)}`;

/** GSTR-9 (annual return) figures from the books, for reference. */
export default function Gstr9Screen() {
  const styles = useThemedStyles(makeStyles);
  const current = fyOf(new Date());
  const years = [current - 1, current, current - 2];
  const [fy, setFy] = useState(current - 1);
  const q = useQuery({ queryKey: ['report-gstr9', fy], queryFn: () => fetchGstr9(fy) });
  const d = q.data;

  return (
    <>
      <Stack.Screen options={{ title: 'GSTR-9' }} />
      <ReportGate>
        <View style={styles.screen}>
          <PeriodBar options={years.map((y) => ({ value: String(y), label: y === current ? `${fyLabel(y)} (so far)` : fyLabel(y) }))}
            value={String(fy)} onChange={(v) => setFy(Number(v))} />
          {q.isLoading ? <Centered /> : q.error || !d ? (
            <EmptyState icon="alert-circle-outline" title="Couldn't load GSTR-9" hint={errorMessage(q.error)} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16, gap: 4 }}
              refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { void q.refetch(); }} />}>
              <Text style={styles.range}>{d.fy_label} · GSTIN {d.gstin || '—'} · {d.sales_counted} sales invoices</Text>

              <IssueSections issues={d.issues} />

              <Section title="4 · Outward supplies with tax payable">
                {d.table4.map((r) => <TaxLine key={r.key} row={r} bold={r.key === '4N'} />)}
              </Section>
              <Section title="5 · Outward supplies with no tax payable">
                {d.table5.map((r) => <TaxLine key={r.key} row={r} bold={r.key === '5N'} />)}
              </Section>
              <Section title="6 · Input tax credit availed">
                {d.table6.map((r) => <TaxLine key={r.key} row={r} showTaxable={false} />)}
              </Section>
              <Section title="7 · Credit reversed">
                {d.table7.map((r) => <TaxLine key={r.key} row={r} showTaxable={false} bold={r.key === '7I'} />)}
                <TaxLine row={d.net_itc} showTaxable={false} bold />
              </Section>
              <Section title={`17 · HSN summary of outward supplies (${d.table17.length})`}>
                {d.table17.map((r) => (
                  <View key={`${r.hsn}-${r.rate}-${r.uqc}`} style={styles.row}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>{r.hsn} · {r.rate}%{r.desc ? ` · ${r.desc}` : ''}</Text>
                      <Text style={styles.sub}>{r.qty} {r.uqc} · {headsText(r)}</Text>
                    </View>
                    <Text style={styles.value}>{money(r.taxable)}</Text>
                  </View>
                ))}
              </Section>

              <Text style={styles.note}>
                From your books, not from the returns as filed: where a return was changed on the portal, the
                portal figure wins. Inputs, capital goods and input services aren’t split in table 6.
              </Text>
            </ScrollView>
          )}
        </View>
      </ReportGate>
    </>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.background },
  range: { fontSize: 12, color: t.textMuted, marginBottom: 10 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border },
  label: { fontSize: 14, color: t.text },
  sub: { fontSize: 12, color: t.textMuted, marginTop: 2 },
  value: { fontSize: 14, color: t.text, fontWeight: '600', fontVariant: ['tabular-nums'], textAlign: 'right' },
  note: { fontSize: 12, color: t.textMuted, textAlign: 'center', marginTop: 10, lineHeight: 17 },
});
