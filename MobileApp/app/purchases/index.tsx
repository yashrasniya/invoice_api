import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack, router } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { InvoiceList } from '@/components/invoice-list';
import { EmptyState } from '@/components/ui/bits';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { useFeature } from '@/hooks/use-access';
import { compactInr } from '@/lib/invoice-calc';
import { fetchPurchaseSummary } from '@/services/purchases';

function Header() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const q = useQuery({ queryKey: ['purchase-summary'], queryFn: fetchPurchaseSummary });
  const s = q.data;
  return (
    <View style={styles.header}>
      <View style={styles.stats}>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>This month</Text>
          <Text style={styles.statValue}>{s ? compactInr(s.this_month_purchases_amount) : '—'}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Input GST (all)</Text>
          <Text style={styles.statValue}>{s ? compactInr(s.total_purchases_gst) : '—'}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Bills</Text>
          <Text style={styles.statValue}>{s ? s.total_count : '—'}</Text>
        </View>
      </View>
      <TouchableOpacity style={styles.scan} onPress={() => router.push('/purchases/scan')}>
        <Ionicons name="scan-outline" size={20} color={theme.onPrimary} />
        <Text style={styles.scanText}>Scan a bill</Text>
      </TouchableOpacity>
    </View>
  );
}

export default function PurchasesScreen() {
  const hasFeature = useFeature('purchases_invoice');
  if (!hasFeature) {
    return (
      <>
        <Stack.Screen options={{ title: 'Purchases' }} />
        <EmptyState icon="lock-closed-outline" title="Purchases are not in your plan" hint="Upgrade your plan on the web to track purchase bills and scan them." />
      </>
    );
  }
  return (
    <>
      <Stack.Screen options={{ title: 'Purchases' }} />
      <InvoiceList type="purchase" header={<Header />} />
    </>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  header: { backgroundColor: t.surface, padding: 16, gap: 12, borderBottomWidth: 1, borderBottomColor: t.border },
  stats: { flexDirection: 'row', gap: 10 },
  stat: { flex: 1, backgroundColor: t.background, borderRadius: 12, padding: 12 },
  statLabel: { fontSize: 11, color: t.textMuted, fontWeight: '600' },
  statValue: { fontSize: 18, fontWeight: '800', color: t.text, marginTop: 2 },
  scan: { height: 48, borderRadius: 14, backgroundColor: t.primary, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  scanText: { color: t.onPrimary, fontWeight: '700', fontSize: 16 },
});
