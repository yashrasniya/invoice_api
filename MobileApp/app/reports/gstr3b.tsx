import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { IssueSections, TaxLine } from '@/components/gst-return-ui';
import { Centered, EmptyState } from '@/components/ui/bits';
import { useThemedStyles, type Theme } from '@/hooks/use-theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { fetchGstr3b, GSTR1_PERIOD_LABEL, Gstr1Period } from '@/services/reports';

const OPTIONS = (Object.keys(GSTR1_PERIOD_LABEL) as Gstr1Period[]).map((v) => ({ value: v, label: GSTR1_PERIOD_LABEL[v] }));

/** GSTR-3B figures to type into the portal. Nothing is filed from here. */
export default function Gstr3bScreen() {
  const styles = useThemedStyles(makeStyles);
  const [period, setPeriod] = useState<Gstr1Period>('last_month');
  const q = useQuery({ queryKey: ['report-gstr3b', period], queryFn: () => fetchGstr3b(period) });
  const d = q.data;

  return (
    <>
      <Stack.Screen options={{ title: 'GSTR-3B' }} />
      <ReportGate>
        <View style={styles.screen}>
          <PeriodBar options={OPTIONS} value={period} onChange={setPeriod} />
          {q.isLoading ? <Centered /> : q.error || !d ? (
            <EmptyState icon="alert-circle-outline" title="Couldn't load GSTR-3B" hint={errorMessage(q.error)} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16, gap: 4 }}
              refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { void q.refetch(); }} />}>
              <Text style={styles.range}>
                {d.period_label} · GSTIN {d.gstin || '—'} · {d.sales_counted} sales, {d.purchases_counted} purchases
              </Text>

              <IssueSections issues={d.issues} />

              <Section title="6.1 · Tax to pay">
                {d.payment.rows.map((r) => (
                  <View key={r.head} style={styles.payRow}>
                    <Text style={[styles.label, { width: 48 }]}>{r.head}</Text>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.sub}>
                        Due {money(r.liability)} · credit used {money(r.paid_igst_credit + r.paid_cgst_credit + r.paid_sgst_credit)}
                        {r.reverse_charge_cash ? ` · reverse charge ${money(r.reverse_charge_cash)}` : ''}
                      </Text>
                    </View>
                    <Text style={styles.value}>{money(r.cash + r.reverse_charge_cash)}</Text>
                  </View>
                ))}
                <View style={styles.payRow}>
                  <Text style={[styles.label, styles.bold, { flex: 1 }]}>Pay in cash</Text>
                  <Text style={[styles.value, styles.bold]}>{money(d.payment.cash_total)}</Text>
                </View>
                <Text style={styles.sub}>
                  Credit carried forward: IGST {money(d.payment.credit_carried_forward.igst)} · CGST{' '}
                  {money(d.payment.credit_carried_forward.cgst)} · SGST {money(d.payment.credit_carried_forward.sgst)}
                </Text>
              </Section>

              <Section title="3.1 · Outward and reverse-charge supplies">
                {d.outward.map((r) => <TaxLine key={r.key} row={r} />)}
                {(d.buyer_pays_reverse_charge.taxable > 0) && (
                  <Text style={[styles.sub, { marginTop: 8 }]}>
                    Not your liability: {money(d.buyer_pays_reverse_charge.taxable)} of supplies where the buyer pays
                    the GST under reverse charge.
                  </Text>
                )}
              </Section>

              {d.inter_state_unregistered.length > 0 && (
                <Section title="3.2 · Inter-state to unregistered / composition">
                  {d.inter_state_unregistered.map((r) => (
                    <View key={`${r.buyer}${r.pos}`} style={styles.payRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.label}>{r.state} ({r.pos})</Text>
                        <Text style={styles.sub}>{r.buyer === 'composition' ? 'Composition dealers' : 'Unregistered'} · IGST {money(r.igst)}</Text>
                      </View>
                      <Text style={styles.value}>{money(r.taxable)}</Text>
                    </View>
                  ))}
                </Section>
              )}

              <Section title="4 · Input tax credit">
                {d.itc.map((r) => <TaxLine key={r.key} row={r} showTaxable={false} bold={r.key === '4C'} />)}
              </Section>

              <Section title="5 · Exempt, nil-rated and non-GST purchases">
                {d.inward_exempt.map((r) => (
                  <View key={r.label} style={styles.payRow}>
                    <Text style={[styles.label, { flex: 1 }]}>{r.label}</Text>
                    <Text style={styles.sub}>Inter {money(r.inter)} · Intra {money(r.intra)}</Text>
                  </View>
                ))}
              </Section>

              <Text style={styles.note}>
                Type these into GSTR-3B on the portal and compare with its auto-filled figures (from GSTR-1 and
                GSTR-2B) before you file. Interest and late fee aren’t included.
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
  payRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border },
  label: { fontSize: 14, color: t.text },
  sub: { fontSize: 12, color: t.textMuted, marginTop: 2 },
  value: { fontSize: 14, color: t.text, fontWeight: '600', fontVariant: ['tabular-nums'], textAlign: 'right' },
  bold: { fontWeight: '800' },
  note: { fontSize: 12, color: t.textMuted, textAlign: 'center', marginTop: 10, lineHeight: 17 },
});
