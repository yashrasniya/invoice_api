import React, { useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack, router } from 'expo-router';
import * as Sharing from 'expo-sharing';
import { PartyPicker } from '@/components/party-picker';
import { PeriodBar, ReportGate } from '@/components/report-ui';
import { Palette } from '@/constants/theme';
import { useFeature } from '@/hooks/use-access';
import { errorMessage } from '@/services/api';
import { exportInvoicesCsv, rangeFor, RANGE_LABEL, RangePreset } from '@/services/reports';
import type { InvoiceType } from '@/services/invoices';
import type { PartyKind } from '@/services/parties';

type CardProps = { icon: keyof typeof Ionicons.glyphMap; title: string; hint: string; onPress: () => void };
const Card = ({ icon, title, hint, onPress }: CardProps) => (
  <TouchableOpacity style={styles.card} onPress={onPress}>
    <View style={styles.iconWrap}><Ionicons name={icon} size={22} color={Palette.primary} /></View>
    <View style={{ flex: 1 }}>
      <Text style={styles.cardTitle}>{title}</Text>
      <Text style={styles.cardHint}>{hint}</Text>
    </View>
    <Ionicons name="chevron-forward" size={18} color={Palette.textFaint} />
  </TouchableOpacity>
);

export default function ReportsHub() {
  const canExport = useFeature('bulk_export');
  const [picking, setPicking] = useState<PartyKind | null>(null);
  const [exportRange, setExportRange] = useState<RangePreset>('this_month');
  const [busy, setBusy] = useState<InvoiceType | null>(null);

  const exportCsv = async (type: InvoiceType) => {
    setBusy(type);
    try {
      const uri = await exportInvoicesCsv(rangeFor(exportRange), type);
      if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing is not available on this device.');
      await Sharing.shareAsync(uri, { mimeType: 'text/csv', dialogTitle: 'Export invoices', UTI: 'public.comma-separated-values-text' });
    } catch (e) {
      Alert.alert('Export failed', errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Stack.Screen options={{ title: 'Reports' }} />
      <ReportGate>
        <ScrollView style={styles.screen} contentContainerStyle={{ padding: 16, gap: 10 }}>
          <Card icon="trending-up" title="Sales report" hint="Totals, trends, top customers, GST" onPress={() => router.push('/reports/sales')} />
          <Card icon="swap-vertical" title="Cash flow" hint="Money in vs money out over time" onPress={() => router.push('/reports/cash-flow')} />
          <Card icon="receipt" title="GST summary" hint="Output vs input GST for filing" onPress={() => router.push('/reports/gst')} />
          <Card icon="people" title="Customer ledger" hint="Statement and outstanding for a customer" onPress={() => setPicking('customer')} />
          <Card icon="business" title="Vendor ledger" hint="Statement and payables for a vendor" onPress={() => setPicking('vendor')} />

          {canExport && (
            <View style={styles.export}>
              <Text style={styles.exportTitle}>Export invoices (CSV)</Text>
              <PeriodBar<RangePreset>
                options={(Object.keys(RANGE_LABEL) as RangePreset[]).map((v) => ({ value: v, label: RANGE_LABEL[v] }))}
                value={exportRange} onChange={setExportRange}
              />
              <View style={{ flexDirection: 'row', gap: 10, marginTop: 12 }}>
                <Card icon="download-outline" title={busy === 'sales' ? 'Preparing…' : 'Sales'} hint="Share as CSV" onPress={() => !busy && exportCsv('sales')} />
              </View>
              <Card icon="download-outline" title={busy === 'purchase' ? 'Preparing…' : 'Purchases'} hint="Share as CSV" onPress={() => !busy && exportCsv('purchase')} />
            </View>
          )}
        </ScrollView>
        <PartyPicker
          kind={picking ?? 'customer'} visible={!!picking} onClose={() => setPicking(null)}
          onPick={(p) => router.push(`/reports/ledger/${picking}/${p.id}`)}
        />
      </ReportGate>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  card: { flexDirection: 'row', alignItems: 'center', gap: 14, backgroundColor: Palette.white, borderRadius: 16, padding: 16, borderWidth: 1, borderColor: Palette.border, flex: 1 },
  iconWrap: { width: 42, height: 42, borderRadius: 12, backgroundColor: '#eef2ff', alignItems: 'center', justifyContent: 'center' },
  cardTitle: { fontSize: 16, fontWeight: '700', color: Palette.text },
  cardHint: { fontSize: 13, color: Palette.textMuted, marginTop: 2 },
  export: { marginTop: 14, gap: 10 },
  exportTitle: { fontSize: 13, fontWeight: '700', color: Palette.textMuted, textTransform: 'uppercase', marginLeft: 4 },
});
