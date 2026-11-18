import React from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import type { PaymentStatus } from '@/services/invoices';
import { STATUS_LABEL } from '@/services/invoices';

const statusColor = (theme: Theme): Record<PaymentStatus, { bg: string; fg: string }> => ({
  paid: { bg: theme.successSoft, fg: theme.successText },
  unpaid: { bg: theme.warningSoft, fg: theme.warningText },
  partially_paid: { bg: theme.infoSoft, fg: theme.infoText },
  overdue: { bg: theme.dangerSoft, fg: theme.dangerText },
});

export function StatusBadge({ status }: { status: PaymentStatus }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeBits);
  const c = statusColor(theme)[status] ?? statusColor(theme).unpaid;
  return (
    <View style={[styles.badge, { backgroundColor: c.bg }]} accessible accessibilityLabel={`Status: ${STATUS_LABEL[status] ?? status}`}>
      <Text style={[styles.badgeText, { color: c.fg }]}>{STATUS_LABEL[status] ?? status}</Text>
    </View>
  );
}

export function Chip({ label, active, onPress }: { label: string; active?: boolean; onPress: () => void }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeBits);
  return (
    <TouchableOpacity onPress={onPress} accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ selected: !!active }} style={[styles.chip, active && styles.chipActive]}>
      <Text style={[styles.chipText, active && { color: theme.onPrimary }]}>{label}</Text>
    </TouchableOpacity>
  );
}

export function EmptyState({ icon, title, hint }: { icon: keyof typeof Ionicons.glyphMap; title: string; hint?: string }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeBits);
  return (
    <View style={styles.empty}>
      <Ionicons name={icon} size={44} color={theme.textFaint} />
      <Text style={styles.emptyTitle}>{title}</Text>
      {!!hint && <Text style={styles.emptyHint}>{hint}</Text>}
    </View>
  );
}

export function Centered({ children }: { children?: React.ReactNode }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeBits);
  return <View style={styles.center}>{children ?? <ActivityIndicator size="large" color={theme.primary} />}</View>;
}

export function Fab({ onPress, icon = 'add', label = 'Add' }: { onPress: () => void; icon?: keyof typeof Ionicons.glyphMap; label?: string }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeBits);
  return (
    <TouchableOpacity style={styles.fab} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={28} color={theme.onPrimary} />
    </TouchableOpacity>
  );
}

const makeBits = (t: Theme) => StyleSheet.create({
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, alignSelf: 'flex-start' },
  badgeText: { fontSize: 12, fontWeight: '700' },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: t.surface, borderWidth: 1, borderColor: t.border },
  chipActive: { backgroundColor: t.primary, borderColor: t.primary },
  chipText: { fontSize: 14, fontWeight: '600', color: t.label },
  empty: { alignItems: 'center', padding: 40, gap: 8 },
  emptyTitle: { fontSize: 17, fontWeight: '700', color: t.text },
  emptyHint: { fontSize: 14, color: t.textMuted, textAlign: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: t.background },
  fab: {
    position: 'absolute', right: 20, bottom: 24, width: 58, height: 58, borderRadius: 29,
    backgroundColor: t.primary, alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 6,
  },
});
