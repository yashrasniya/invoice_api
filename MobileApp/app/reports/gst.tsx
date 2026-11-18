import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Kpi, KpiGrid, PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { Centered, EmptyState } from '@/components/ui/bits';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { fetchGstSummary, GST_PERIOD_LABEL, GstIssue, GstPeriod } from '@/services/reports';

const OPTIONS = (Object.keys(GST_PERIOD_LABEL) as GstPeriod[]).map((v) => ({ value: v, label: GST_PERIOD_LABEL[v] }));

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.row}>
      <Text style={[styles.label, bold && styles.bold]}>{label}</Text>
      <Text style={[styles.value, bold && styles.bold]}>{value}</Text>
    </View>
  );
}

/** A problem the server found that makes these figures unsafe to file as they stand. */
function Issue({ issue }: { issue: GstIssue }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const tone = issue.level === 'error' ? theme.danger : theme.warning;
  return (
    <View style={[styles.issue, { borderColor: tone }]} accessibilityRole="alert">
      <Text style={[styles.issueTitle, { color: tone }]}>{issue.title}</Text>
      <Text style={styles.issueText}>{issue.detail}</Text>
      {!!issue.fix && <Text style={styles.issueFix}>Fix: {issue.fix}</Text>}
    </View>
  );
}

export default function GstScreen() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
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
            <ScrollView contentContainerStyle={{ padding: 16 }} refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { void q.refetch(); }} />}>
              <Text style={styles.range}>{d.period_label} · {d.start_date} → {d.end_date}</Text>
              {(d.data_quality ?? []).map((issue) => <Issue key={issue.code} issue={issue} />)}
              <KpiGrid>
                <Kpi wide label={d.net_gst_payable >= 0 ? 'Net GST payable' : 'Net GST credit'} value={money(Math.abs(d.net_gst_payable))}
                  tone={d.net_gst_payable >= 0 ? theme.danger : theme.success} />
                <Kpi label="Output GST (sales)" value={money(d.output_gst + (d.output_tax_adjustment ?? 0))} />
                <Kpi label="Input GST (purchases)" value={money(d.input_gst + (d.input_tax_adjustment ?? 0))} />
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
              {(d.credit_note_count > 0 || d.debit_note_count > 0) && (
                <Section title="Credit & debit notes">
                  <Row label={`Credit notes (${d.credit_note_count})`} value={money(d.credit_note_value)} />
                  <Row label={`Debit notes (${d.debit_note_count})`} value={money(d.debit_note_value)} />
                  {d.output_tax_adjustment !== 0 && <Row label="Change to output GST" value={money(d.output_tax_adjustment)} />}
                  {d.input_tax_adjustment !== 0 && <Row label="Change to input GST" value={money(d.input_tax_adjustment)} />}
                  {d.notes_without_gst > 0 && (
                    <Text style={styles.note}>{d.notes_without_gst} note(s) have no GST amount and are not included above.</Text>
                  )}
                </Section>
              )}
              <Text style={styles.note}>Figures are in whole rupees. Review with your accountant before filing.</Text>
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
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingVertical: 6 },
  label: { fontSize: 14, color: t.text, flex: 1 },
  value: { fontSize: 14, color: t.text, fontWeight: '600' },
  bold: { fontWeight: '800' },
  note: { fontSize: 12, color: t.textMuted, textAlign: 'center', marginTop: 4 },
  issue: { borderWidth: 1.5, borderRadius: 14, padding: 12, marginBottom: 10, backgroundColor: t.surface },
  issueTitle: { fontSize: 14, fontWeight: '800', marginBottom: 4 },
  issueText: { fontSize: 13, color: t.text, lineHeight: 18 },
  issueFix: { fontSize: 12, color: t.textMuted, marginTop: 6, fontWeight: '600' },
});
