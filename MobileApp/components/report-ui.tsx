import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Chip, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';

/** Horizontal chip row for choosing a period/range preset. */
export function PeriodBar<T extends string>({ options, value, onChange }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.bar} contentContainerStyle={{ gap: 8, paddingHorizontal: 16, paddingVertical: 12 }}>
      {options.map((o) => <Chip key={o.value} label={o.label} active={o.value === value} onPress={() => onChange(o.value)} />)}
    </ScrollView>
  );
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

export function Kpi({ label, value, tone, wide }: { label: string; value: string; tone?: string; wide?: boolean }) {
  return (
    <View style={[styles.kpi, wide && { width: '100%' }]}>
      <Text style={styles.kpiLabel}>{label}</Text>
      <Text style={[styles.kpiValue, tone ? { color: tone } : null]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
    </View>
  );
}

export const KpiGrid = ({ children }: { children: React.ReactNode }) => <View style={styles.grid}>{children}</View>;

/**
 * Hides report screens the user cannot use. The server enforces the same two rules
 * (plan feature + report.view); this just explains it instead of showing a raw 403.
 */
export function ReportGate({ children }: { children: React.ReactNode }) {
  const hasFeature = useFeature('advanced_reports');
  const canView = useCan('report.view');
  if (!hasFeature) {
    return <EmptyState icon="lock-closed-outline" title="Reports are not in your plan" hint="Upgrade your plan on the web to unlock sales, GST and ledger reports." />;
  }
  if (!canView) return <EmptyState icon="lock-closed-outline" title="No access" hint="You don't have permission to view reports." />;
  return <>{children}</>;
}

const styles = StyleSheet.create({
  bar: { flexGrow: 0, backgroundColor: Palette.white, borderBottomWidth: 1, borderBottomColor: Palette.border },
  section: { backgroundColor: Palette.white, borderRadius: 16, padding: 16, marginBottom: 14, borderWidth: 1, borderColor: Palette.border },
  sectionTitle: { fontSize: 15, fontWeight: '800', color: Palette.text, marginBottom: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 14 },
  kpi: { width: '48%', flexGrow: 1, backgroundColor: Palette.white, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: Palette.border },
  kpiLabel: { fontSize: 12, color: Palette.textMuted, fontWeight: '600' },
  kpiValue: { fontSize: 20, fontWeight: '800', color: Palette.text, marginTop: 4 },
});
