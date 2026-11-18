import React, { useState } from 'react';
import { Alert, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Stack, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import * as Sharing from 'expo-sharing';
import { PeriodBar, ReportGate, Section } from '@/components/report-ui';
import { Button } from '@/components/ui/button';
import { Centered, Chip, EmptyState } from '@/components/ui/bits';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { downloadGstr1, fetchGstr1, GSTR1_PERIOD_LABEL, Gstr1Issue, Gstr1Period } from '@/services/reports';

const OPTIONS = (Object.keys(GSTR1_PERIOD_LABEL) as Gstr1Period[]).map((v) => ({ value: v, label: GSTR1_PERIOD_LABEL[v] }));

/** One thing to fix. Tapping an invoice issue opens that invoice. */
function IssueRow({ issue }: { issue: Gstr1Issue }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const tone = issue.level === 'error' ? theme.danger : theme.warning;
  const ref = issue.ref;
  const open = ref?.kind === 'invoice' ? () => router.push(`/invoice/${ref.id}`) : undefined;
  return (
    <TouchableOpacity style={styles.issue} onPress={open} disabled={!open} accessibilityRole={open ? 'button' : undefined}>
      <Ionicons name={issue.level === 'error' ? 'close-circle' : 'alert-circle'} size={18} color={tone} />
      <View style={{ flex: 1 }}>
        {!!ref && (
          <Text style={styles.issueRef}>
            {ref.kind === 'note' ? 'Note' : 'Invoice'} {ref.number || `#${ref.id}`}{ref.date ? ` · ${ref.date}` : ''}
          </Text>
        )}
        <Text style={styles.issueText}>{issue.message}</Text>
      </View>
      {!!open && <Ionicons name="chevron-forward" size={16} color={theme.textFaint} />}
    </TouchableOpacity>
  );
}

export default function Gstr1Screen() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const [period, setPeriod] = useState<Gstr1Period>('last_month');
  const [sharing, setSharing] = useState(false);
  // quarterly filer's quarter: B2B of the first two months was sent in the IFF unless this is on
  const [includeIff, setIncludeIff] = useState(false);
  const q = useQuery({ queryKey: ['report-gstr1', period, includeIff], queryFn: () => fetchGstr1(period, includeIff) });
  const d = q.data;

  const share = async () => {
    if (!d) return;
    setSharing(true);
    try {
      const uri = await downloadGstr1(period, d.gstin, d.fp, includeIff, d.return_type);
      if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing is not available on this device.');
      await Sharing.shareAsync(uri, { mimeType: 'application/json', dialogTitle: 'GSTR-1 file', UTI: 'public.json' });
    } catch (e) {
      Alert.alert('Could not prepare the file', errorMessage(e));
    } finally {
      setSharing(false);
    }
  };

  const errors = d?.issues.filter((i) => i.level === 'error') ?? [];
  const warnings = d?.issues.filter((i) => i.level === 'warning') ?? [];

  return (
    <>
      <Stack.Screen options={{ title: d?.return_type === 'IFF' ? 'IFF (GSTR-1)' : 'GSTR-1' }} />
      <ReportGate>
        <View style={styles.screen}>
          <PeriodBar options={OPTIONS} value={period} onChange={setPeriod} />
          {q.isLoading ? <Centered /> : q.error || !d ? (
            <EmptyState icon="alert-circle-outline" title="Couldn't load GSTR-1" hint={errorMessage(q.error)} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16, gap: 4 }}
              refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { void q.refetch(); }} />}>
              <Text style={styles.range}>{d.period_label} · GSTIN {d.gstin || '—'}</Text>
              {d.return_type === 'IFF' && (
                <Text style={styles.banner}>
                  You file quarterly, so this month is the IFF: B2B invoices and their notes only. B2C sales go in the
                  quarterly GSTR-1.
                </Text>
              )}
              {d.filing_frequency === 'quarterly' && period.endsWith('quarter') && (
                <View style={styles.iffRow}>
                  <Text style={[styles.sub, { flex: 1 }]}>
                    {includeIff ? 'Including' : 'Leaving out'} B2B invoices of the quarter’s first two months
                    {includeIff ? '.' : ' (already sent in the IFF).'}
                  </Text>
                  <Chip label={includeIff ? 'Leave them out' : 'Include them'} active={false} onPress={() => setIncludeIff((v) => !v)} />
                </View>
              )}

              <View style={[styles.status, { borderColor: d.ready_to_file ? theme.success : theme.danger }]}>
                <Ionicons name={d.ready_to_file ? 'checkmark-circle' : 'close-circle'} size={22}
                  color={d.ready_to_file ? theme.success : theme.danger} />
                <Text style={styles.statusText}>
                  {d.ready_to_file
                    ? `Ready to file${d.warning_count ? ` · ${d.warning_count} warning(s) to review` : ''}`
                    : `${d.error_count} error(s) to fix before filing`}
                </Text>
              </View>

              <Section title="Tables">
                {d.tables.map((t) => (
                  <View key={t.table} style={styles.tableRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>{t.label}</Text>
                      <Text style={styles.sub}>{t.count ? `${t.count} invoice(s) · ` : ''}taxable {money(t.taxable)}</Text>
                    </View>
                    <Text style={styles.value}>{money(t.tax)}</Text>
                  </View>
                ))}
                <View style={styles.tableRow}>
                  <Text style={[styles.label, styles.bold, { flex: 1 }]}>Total tax</Text>
                  <Text style={[styles.value, styles.bold]}>{money(d.total_tax)}</Text>
                </View>
                <Text style={styles.sub}>Table 12 (HSN): {d.hsn_rows} row(s) · Table 13: {d.documents.length} series</Text>
              </Section>

              {errors.length > 0 && (
                <Section title={`Fix before filing (${errors.length})`}>
                  {errors.map((i, n) => <IssueRow key={`e${n}`} issue={i} />)}
                </Section>
              )}
              {warnings.length > 0 && (
                <Section title={`Review (${warnings.length})`}>
                  {warnings.map((i, n) => <IssueRow key={`w${n}`} issue={i} />)}
                </Section>
              )}

              <Button title={sharing ? 'Preparing…' : `Share ${d.return_type} JSON`} onPress={share}
                disabled={!d.ready_to_file || sharing} />
              <Text style={styles.note}>
                Upload the file on the GST portal (Returns → GSTR-1 → Prepare offline → Upload). Check the portal
                summary against this screen before submitting.
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
  status: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1.5, borderRadius: 14, padding: 12, marginBottom: 12, backgroundColor: t.surface },
  statusText: { fontSize: 15, fontWeight: '700', color: t.text, flex: 1 },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 7 },
  label: { fontSize: 14, color: t.text },
  sub: { fontSize: 12, color: t.textMuted, marginTop: 2 },
  value: { fontSize: 14, color: t.text, fontWeight: '600' },
  bold: { fontWeight: '800' },
  issue: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border },
  issueRef: { fontSize: 12, fontWeight: '700', color: t.textMuted, marginBottom: 2 },
  issueText: { fontSize: 13, color: t.text, lineHeight: 18 },
  banner: { fontSize: 13, color: t.text, backgroundColor: t.primarySoft, borderRadius: 12, padding: 12, marginBottom: 12, lineHeight: 18 },
  iffRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 12 },
  note: { fontSize: 12, color: t.textMuted, textAlign: 'center', marginTop: 10, lineHeight: 17 },
});
