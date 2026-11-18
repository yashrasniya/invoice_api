import React, { useState } from 'react';
import { FlatList, Modal, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { GST_STATES } from '@/constants/gst';

type State = { code: number; name: string };

type Props = { label: string; value: number | null; onChange: (code: number) => void; error?: string; states?: State[];
  /** Shown under the field; with `locked`, the state can't be changed (e.g. it comes from the GSTIN). */
  hint?: string; locked?: boolean };

/** A field that opens a searchless full-height list of GST states — 37 entries, so a list beats chips. */
export function StatePicker({ label, value, onChange, error, states = GST_STATES, hint, locked }: Props) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const [open, setOpen] = useState(false);
  const insets = useSafeAreaInsets();
  const selected = states.find((s) => s.code === value);

  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <TouchableOpacity
        accessibilityRole="button" accessibilityLabel={label}
        style={[styles.field, !!error && { borderColor: theme.danger }, locked && { opacity: 0.7 }]} onPress={() => !locked && setOpen(true)}
        accessibilityState={{ disabled: !!locked }}>
        <Text style={[styles.value, !selected && { color: theme.textFaint }]} numberOfLines={1}>
          {selected ? `${selected.name} (${String(selected.code).padStart(2, '0')})` : 'Select state'}
        </Text>
        <Ionicons name={locked ? 'lock-closed' : 'chevron-down'} size={locked ? 16 : 20} color={theme.textMuted} />
      </TouchableOpacity>
      {!!error && <Text style={styles.error}>{error}</Text>}
      {!error && !!hint && <Text style={styles.hint}>{hint}</Text>}

      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={[styles.sheet, { paddingTop: insets.top + 12 }]}>
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>Select state</Text>
            <TouchableOpacity onPress={() => setOpen(false)} hitSlop={12} accessibilityLabel="Close">
              <Ionicons name="close" size={26} color={theme.text} />
            </TouchableOpacity>
          </View>
          <FlatList
            data={[...states].sort((a, b) => a.name.localeCompare(b.name))}
            keyExtractor={(s) => String(s.code)}
            contentContainerStyle={{ paddingBottom: insets.bottom + 16 }}
            renderItem={({ item }) => (
              <TouchableOpacity style={styles.row} onPress={() => { onChange(item.code); setOpen(false); }}>
                <Text style={[styles.rowText, item.code === value && { color: theme.primary, fontWeight: '800' }]}>{item.name}</Text>
                <Text style={styles.code}>{String(item.code).padStart(2, '0')}</Text>
              </TouchableOpacity>
            )}
          />
        </View>
      </Modal>
    </View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  group: { marginBottom: 18 },
  label: { fontSize: 14, fontWeight: '700', color: t.label, marginBottom: 8, marginLeft: 4 },
  field: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, height: 56,
    backgroundColor: t.isDark ? t.surfaceRaised : t.background, borderWidth: 1.5, borderColor: t.border, borderRadius: 16, paddingHorizontal: 16,
  },
  value: { flex: 1, fontSize: 16, fontWeight: '500', color: t.text },
  error: { color: t.danger, fontSize: 13, marginTop: 6, marginLeft: 4 },
  hint: { color: t.textMuted, fontSize: 12, marginTop: 6, marginLeft: 4 },
  sheet: { flex: 1, backgroundColor: t.surface },
  sheetHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingBottom: 12 },
  sheetTitle: { fontSize: 20, fontWeight: '800', color: t.text },
  row: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20, paddingVertical: 14,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border,
  },
  rowText: { fontSize: 16, color: t.text, flex: 1 },
  code: { fontSize: 14, color: t.textMuted },
});
