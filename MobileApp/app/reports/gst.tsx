import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Kpi, KpiGrid, PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { fetchGstSummary, GST_PERIOD_LABEL, GstPeriod } from '@/services/reports';

const OPTIONS = (Object.keys(GST_PERIOD_LABEL) as GstPeriod[]).map((v) => ({ value: v, label: GST_PERIOD_LABEL[v] }));

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={[styles.label, bold && styles.bold]}>{label}</Text>
      <Text style={[styles.value, bold && styles.bold]}>{value}</Text>
    </View>
  );
}

export default function GstScreen() {
  const [period, setPeriod] = useState<GstPeriod>('this_month');
  const q = useQuery({ queryKey: ['report-gst', period], queryFn: () => fetchGstSummary(period) });
  const d = q.data;

  return (
    <>
      <Stack.Screen options={{ title: 'GST summary' }} />
      <ReportGate>
        <View style={styles.screen}>
          <PeriodBar options={OPTIONS} value={period} onChange={setPeriod} />
          {q.isLoading ? <Centered /> : q.error || !d ? (
            <EmptyState icon="alert-circle-outline" title="Couldn't load report" hint={errorMessage(q.error)} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16 }} refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} />}>
              <Text style={styles.range}>{d.period_label} · {d.start_date} → {d.end_date}</Text>
              <KpiGrid>
                <Kpi wide label={d.net_gst_payable >= 0 ? 'Net GST payable' : 'Net GST credit'} value={money(Math.abs(d.net_gst_payable))}
                  tone={d.net_gst_payable >= 0 ? Palette.danger : Palette.success} />
                <Kpi label="Output GST (sales)" value={money(d.output_gst)} />
                <Kpi label="Input GST (purchases)" value={money(d.input_gst)} />
              </KpiGrid>
              <Section title="Taxable value">
                <Row label={`Sales (${d.sales_invoice_count} invoices)`} value={money(d.total_sales_taxable)} />
                <Row label={`Purchases (${d.purchase_invoice_count} bills)`} value={money(d.total_purchases_taxable)} />
              </Section>
              <Section title="Output tax split">
                <Row label="CGST" value={money(d.tax_split.cgst)} />
                <Row label="SGST" value={money(d.tax_split.sgst)} />
                <Row label="IGST" value={money(d.tax_split.igst)} />
                {d.tax_split.unclassified > 0 && (
                  <Row label={`Unclassified (${d.tax_split.unclassified_invoices} invoices missing a customer state)`} value={money(d.tax_split.unclassified)} />
                )}
              </Section>
              <Text style={styles.note}>Figures are in whole rupees. Review with your accountant before filing.</Text>
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
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingVertical: 6 },
  label: { fontSize: 14, color: Palette.text, flex: 1 },
  value: { fontSize: 14, color: Palette.text, fontWeight: '600' },
  bold: { fontWeight: '800' },
  note: { fontSize: 12, color: Palette.textMuted, textAlign: 'center', marginTop: 4 },
});
