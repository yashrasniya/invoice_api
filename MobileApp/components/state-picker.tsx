import React, { useState } from 'react';
import { FlatList, Modal, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Palette } from '@/constants/theme';
import { GST_STATES } from '@/constants/gst';

type Props = { label: string; value: number | null; onChange: (code: number) => void; error?: string };

/** A field that opens a searchless full-height list of GST states — 37 entries, so a list beats chips. */
export function StatePicker({ label, value, onChange, error }: Props) {
  const [open, setOpen] = useState(false);
  const insets = useSafeAreaInsets();
  const selected = GST_STATES.find((s) => s.code === value);

  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <TouchableOpacity
        accessibilityRole="button" accessibilityLabel={label}
        style={[styles.field, !!error && { borderColor: Palette.danger }]} onPress={() => setOpen(true)}>
        <Text style={[styles.value, !selected && { color: Palette.textFaint }]} numberOfLines={1}>
          {selected ? `${selected.name} (${String(selected.code).padStart(2, '0')})` : 'Select state'}
        </Text>
        <Ionicons name="chevron-down" size={20} color={Palette.textMuted} />
      </TouchableOpacity>
      {!!error && <Text style={styles.error}>{error}</Text>}

      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={[styles.sheet, { paddingTop: insets.top + 12 }]}>
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>Select state</Text>
            <TouchableOpacity onPress={() => setOpen(false)} hitSlop={12} accessibilityLabel="Close">
              <Ionicons name="close" size={26} color={Palette.text} />
            </TouchableOpacity>
          </View>
          <FlatList
            data={[...GST_STATES].sort((a, b) => a.name.localeCompare(b.name))}
            keyExtractor={(s) => String(s.code)}
            contentContainerStyle={{ paddingBottom: insets.bottom + 16 }}
            renderItem={({ item }) => (
              <TouchableOpacity style={styles.row} onPress={() => { onChange(item.code); setOpen(false); }}>
                <Text style={[styles.rowText, item.code === value && { color: Palette.primary, fontWeight: '800' }]}>{item.name}</Text>
                <Text style={styles.code}>{String(item.code).padStart(2, '0')}</Text>
              </TouchableOpacity>
            )}
          />
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: 18 },
  label: { fontSize: 14, fontWeight: '700', color: Palette.label, marginBottom: 8, marginLeft: 4 },
  field: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, height: 56,
    backgroundColor: Palette.surface, borderWidth: 1.5, borderColor: Palette.border, borderRadius: 16, paddingHorizontal: 16,
  },
  value: { flex: 1, fontSize: 16, fontWeight: '500', color: Palette.text },
  error: { color: Palette.danger, fontSize: 13, marginTop: 6, marginLeft: 4 },
  sheet: { flex: 1, backgroundColor: Palette.white },
  sheetHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingBottom: 12 },
  sheetTitle: { fontSize: 20, fontWeight: '800', color: Palette.text },
  row: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20, paddingVertical: 14,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: Palette.border,
  },
  rowText: { fontSize: 16, color: Palette.text, flex: 1 },
  code: { fontSize: 14, color: Palette.textMuted },
});
