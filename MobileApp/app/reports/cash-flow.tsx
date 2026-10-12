import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Legend } from '@/components/charts';
import { Kpi, KpiGrid, PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { fetchCashFlow, Interval, rangeFor, RANGE_LABEL, RangePreset } from '@/services/reports';

const OPTIONS = (Object.keys(RANGE_LABEL) as RangePreset[]).map((v) => ({ value: v, label: RANGE_LABEL[v] }));
const INTERVALS: { value: Interval; label: string }[] = [
  { value: 'daily', label: 'Daily' }, { value: 'weekly', label: 'Weekly' }, { value: 'monthly', label: 'Monthly' },
];

export default function CashFlowScreen() {
  const [preset, setPreset] = useState<RangePreset>('last_30');
  const [interval, setInterval] = useState<Interval>('daily');
  const range = rangeFor(preset);
  const q = useQuery({ queryKey: ['report-cash', range, interval], queryFn: () => fetchCashFlow(range, interval) });
  const rows = q.data ?? [];
  const inflow = rows.reduce((s, r) => s + r.inflow, 0);
  const outflow = rows.reduce((s, r) => s + r.outflow, 0);
  const net = inflow - outflow;

  return (
    <>
      <Stack.Screen options={{ title: 'Cash flow' }} />
      <ReportGate>
        <View style={styles.screen}>
          <PeriodBar options={OPTIONS} value={preset} onChange={setPreset} />
          <PeriodBar options={INTERVALS} value={interval} onChange={setInterval} />
          {q.isLoading ? <Centered /> : q.error ? (
            <EmptyState icon="alert-circle-outline" title="Couldn't load report" hint={errorMessage(q.error)} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16 }} refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} />}>
              <KpiGrid>
                <Kpi label="Money in" value={money(inflow)} tone={Palette.success} />
                <Kpi label="Money out" value={money(outflow)} tone={Palette.danger} />
                <Kpi wide label="Net" value={money(net)} tone={net < 0 ? Palette.danger : Palette.success} />
              </KpiGrid>
              <Section title="In vs out">
                <BarChart
                  colors={[Palette.success, Palette.danger]}
                  barWidth={interval === 'daily' ? 6 : 14}
                  data={rows.map((r) => ({ label: r.date.slice(interval === 'monthly' ? 0 : 5, interval === 'monthly' ? 7 : 10), values: [r.inflow, r.outflow] }))}
                />
                <Legend items={[{ label: 'In (sales)', color: Palette.success }, { label: 'Out (purchases)', color: Palette.danger }]} />
              </Section>
              <Text style={styles.note}>Based on invoice dates and totals, not on payments received.</Text>
            </ScrollView>
          )}
        </View>
      </ReportGate>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  note: { fontSize: 12, color: Palette.textMuted, textAlign: 'center' },
});
