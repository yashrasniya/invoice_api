import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { BarChart, HBarList } from '@/components/charts';
import { Kpi, KpiGrid, PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { compactInr, money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { fetchSalesReport, rangeFor, RANGE_LABEL, RangePreset } from '@/services/reports';

const OPTIONS = (Object.keys(RANGE_LABEL) as RangePreset[]).map((v) => ({ value: v, label: RANGE_LABEL[v] }));
const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

export default function SalesReportScreen() {
  const [preset, setPreset] = useState<RangePreset>('this_month');
  const range = rangeFor(preset);
  const q = useQuery({ queryKey: ['report-sales', range], queryFn: () => fetchSalesReport(range) });
  const d = q.data;

  return (
    <>
      <Stack.Screen options={{ title: 'Sales report' }} />
      <ReportGate>
        <View style={styles.screen}>
          <PeriodBar options={OPTIONS} value={preset} onChange={setPreset} />
          {q.isLoading ? <Centered /> : q.error || !d ? (
            <EmptyState icon="alert-circle-outline" title="Couldn't load report" hint={errorMessage(q.error)} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16 }} refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} />}>
              <Text style={styles.range}>{range.start_date} → {range.end_date}</Text>
              <KpiGrid>
                <Kpi wide label="Total sales" value={money(d.summary.total_sales)} />
                <Kpi label="Invoices" value={String(d.summary.total_invoices)} />
                <Kpi label="Avg. invoice" value={money(d.summary.average_invoice_value)} />
                <Kpi label="Paid" value={money(d.summary.paid_amount)} tone={Palette.success} />
                <Kpi label="Unpaid" value={money(d.summary.unpaid_amount)} />
                <Kpi label="Overdue" value={money(d.summary.overdue_amount)} tone={d.summary.overdue_amount > 0 ? Palette.danger : undefined} />
                <Kpi label="GST collected" value={money(d.summary.gst_collected)} />
              </KpiGrid>

              <Section title="Sales trend">
                {d.charts.sales_trend.length === 0 ? <Text style={styles.empty}>No sales in this period.</Text> : (
                  <BarChart data={d.charts.sales_trend.map((p) => ({ label: p.date.slice(5), values: [p.sales] }))} />
                )}
              </Section>

              {d.charts.top_customers.length > 0 && (
                <Section title="Top customers">
                  <HBarList items={d.charts.top_customers.map((c) => ({ label: c.name, value: c.sales }))} />
                </Section>
              )}
              {d.charts.payment_status_distribution.length > 0 && (
                <Section title="By payment status">
                  <HBarList color={Palette.primaryAlt} items={d.charts.payment_status_distribution.map((c) => ({ label: titleCase(c.name), value: c.value }))} />
                </Section>
              )}
              {d.charts.payment_method_distribution.length > 0 && (
                <Section title="By payment method">
                  <HBarList color={Palette.success} items={d.charts.payment_method_distribution.map((c) => ({ label: titleCase(c.name), value: c.value }))} />
                </Section>
              )}
              {d.charts.sales_by_state.length > 0 && (
                <Section title="By state">
                  <HBarList color="#0ea5e9" items={d.charts.sales_by_state.slice(0, 8).map((c) => ({ label: c.state, value: c.sales }))} />
                </Section>
              )}
              <Section title="Highlights">
                <Text style={styles.line}>Top customer: <Text style={styles.bold}>{d.summary.top_customer}</Text></Text>
                <Text style={styles.line}>Best day: <Text style={styles.bold}>{d.summary.highest_sale_day}</Text></Text>
                <Text style={styles.line}>Growth vs previous period: <Text style={styles.bold}>{d.summary.sales_growth_pct.toFixed(1)}%</Text></Text>
                <Text style={styles.line}>New customers: <Text style={styles.bold}>{d.kpis.new_customers}</Text> · Repeat: <Text style={styles.bold}>{d.kpis.repeat_customer_pct.toFixed(0)}%</Text></Text>
                {d.summary.credit_notes_issued > 0 && (
                  <Text style={styles.line}>Credit notes: <Text style={styles.bold}>{d.summary.credit_notes_issued}</Text> ({compactInr(d.summary.credit_notes_amount)})</Text>
                )}
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
  range: { fontSize: 12, color: Palette.textMuted, marginBottom: 10 },
  empty: { color: Palette.textMuted },
  line: { fontSize: 14, color: Palette.text, marginBottom: 6 },
  bold: { fontWeight: '700' },
});
