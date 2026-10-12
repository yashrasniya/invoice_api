import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { HBarList } from '@/components/charts';
import { Kpi, KpiGrid, PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { fetchLedger, GST_PERIOD_LABEL, GstPeriod, LedgerPeriod } from '@/services/reports';

const OPTIONS: { value: LedgerPeriod; label: string }[] = [
  ...(Object.keys(GST_PERIOD_LABEL) as GstPeriod[]).map((v) => ({ value: v as LedgerPeriod, label: GST_PERIOD_LABEL[v] })),
  { value: 'all_time', label: 'All time' },
];

export default function LedgerScreen() {
  const { kind: rawKind, id } = useLocalSearchParams<{ kind: string; id: string }>();
  const kind = rawKind === 'vendor' ? 'vendor' : 'customer';
  const [period, setPeriod] = useState<LedgerPeriod>('this_fy');
  const q = useQuery({ queryKey: ['ledger', kind, id, period], queryFn: () => fetchLedger(kind, Number(id), period) });
  const d = q.data;
  const receivable = kind === 'customer';

  return (
    <>
      <Stack.Screen options={{ title: d?.party.name ?? (receivable ? 'Customer ledger' : 'Vendor ledger') }} />
      <ReportGate>
        <View style={styles.screen}>
          <PeriodBar options={OPTIONS} value={period} onChange={setPeriod} />
          {q.isLoading ? <Centered /> : q.error || !d ? (
            <EmptyState icon="alert-circle-outline" title="Couldn't load ledger" hint={errorMessage(q.error)} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16 }} refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} />}>
              <KpiGrid>
                <Kpi wide label={receivable ? 'Outstanding (they owe you)' : 'Outstanding (you owe)'} value={money(d.outstanding_total)}
                  tone={d.outstanding_total > 0 ? Palette.danger : Palette.success} />
                <Kpi label="Opening balance" value={money(d.opening_balance)} />
                <Kpi label="Closing balance" value={money(d.closing_balance)} />
                <Kpi label="Lifetime billed" value={money(d.lifetime.billed)} />
                <Kpi label="Settled" value={money(d.lifetime.settled)} />
              </KpiGrid>

              {d.outstanding_count > 0 && (
                <Section title={`Ageing · ${d.outstanding_count} open`}>
                  <HBarList color={Palette.danger} items={d.ageing.filter((b) => b.amount > 0).map((b) => ({ label: `${b.label} (${b.count})`, value: b.amount }))} />
                </Section>
              )}

              <Section title={`Statement · ${d.period_label}`}>
                {d.transactions.length === 0 && <Text style={styles.empty}>No transactions in this period.</Text>}
                {d.transactions.map((t, i) => (
                  <View key={i} style={[styles.tx, i > 0 && styles.txBorder]}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.txTitle} numberOfLines={1}>{t.particulars || t.vch_type}</Text>
                      <Text style={styles.txMeta}>{t.date} · {t.vch_type}</Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={[styles.txAmt, { color: t.credit > 0 ? Palette.success : Palette.text }]}>
                        {t.debit > 0 ? `Dr ${money(t.debit)}` : `Cr ${money(t.credit)}`}
                      </Text>
                      <Text style={styles.txMeta}>Bal {money(t.balance)}</Text>
                    </View>
                  </View>
                ))}
              </Section>
            </ScrollView>
          )}
        </View>
      </ReportGate>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  empty: { color: Palette.textMuted },
  tx: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10 },
  txBorder: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: Palette.border },
  txTitle: { fontSize: 14, fontWeight: '600', color: Palette.text },
  txMeta: { fontSize: 12, color: Palette.textMuted, marginTop: 2 },
  txAmt: { fontSize: 14, fontWeight: '700' },
});
