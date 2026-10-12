import React from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette } from '@/constants/theme';
import type { PaymentStatus } from '@/services/invoices';
import { STATUS_LABEL } from '@/services/invoices';

const STATUS_COLOR: Record<PaymentStatus, { bg: string; fg: string }> = {
  paid: { bg: '#dcfce7', fg: '#166534' },
  unpaid: { bg: '#fef3c7', fg: '#92400e' },
  partially_paid: { bg: '#dbeafe', fg: '#1e40af' },
  overdue: { bg: '#fee2e2', fg: '#991b1b' },
};

export function StatusBadge({ status }: { status: PaymentStatus }) {
  const c = STATUS_COLOR[status] ?? STATUS_COLOR.unpaid;
  return (
    <View style={[bits.badge, { backgroundColor: c.bg }]} accessible accessibilityLabel={`Status: ${STATUS_LABEL[status] ?? status}`}>
      <Text style={[bits.badgeText, { color: c.fg }]}>{STATUS_LABEL[status] ?? status}</Text>
    </View>
  );
}

export function Chip({ label, active, onPress }: { label: string; active?: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity onPress={onPress} accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ selected: !!active }} style={[bits.chip, active && bits.chipActive]}>
      <Text style={[bits.chipText, active && { color: Palette.white }]}>{label}</Text>
    </TouchableOpacity>
  );
}

export function EmptyState({ icon, title, hint }: { icon: keyof typeof Ionicons.glyphMap; title: string; hint?: string }) {
  return (
    <View style={bits.empty}>
      <Ionicons name={icon} size={44} color={Palette.textFaint} />
      <Text style={bits.emptyTitle}>{title}</Text>
      {!!hint && <Text style={bits.emptyHint}>{hint}</Text>}
    </View>
  );
}

export function Centered({ children }: { children?: React.ReactNode }) {
  return <View style={bits.center}>{children ?? <ActivityIndicator size="large" color={Palette.primary} />}</View>;
}

export function Fab({ onPress, icon = 'add', label = 'Add' }: { onPress: () => void; icon?: keyof typeof Ionicons.glyphMap; label?: string }) {
  return (
    <TouchableOpacity style={bits.fab} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={28} color={Palette.white} />
    </TouchableOpacity>
  );
}

export const bits = StyleSheet.create({
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, alignSelf: 'flex-start' },
  badgeText: { fontSize: 12, fontWeight: '700' },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: Palette.white, borderWidth: 1, borderColor: Palette.border },
  chipActive: { backgroundColor: Palette.primary, borderColor: Palette.primary },
  chipText: { fontSize: 14, fontWeight: '600', color: Palette.label },
  empty: { alignItems: 'center', padding: 40, gap: 8 },
  emptyTitle: { fontSize: 17, fontWeight: '700', color: Palette.text },
  emptyHint: { fontSize: 14, color: Palette.textMuted, textAlign: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: Palette.surface },
  fab: {
    position: 'absolute', right: 20, bottom: 24, width: 58, height: 58, borderRadius: 29,
    backgroundColor: Palette.primary, alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 6,
  },
});
