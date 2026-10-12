import React, { useEffect, useMemo, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Button } from '@/components/ui/button';
import { Chip } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { calculateLine, money } from '@/lib/invoice-calc';
import { InventoryPicker } from '@/components/inventory-picker';
import type { InventoryProduct } from '@/services/inventory';
import type { Column, NewLine } from '@/services/invoices';

type Props = {
  visible: boolean;
  columns: Column[];
  onClose: () => void;
  onSave: (line: NewLine) => void;
  /** show the "pick from inventory" shortcut */
  useInventory?: boolean;
  /** editing an existing line: pre-fill these values (by column id) instead of the defaults */
  initialValues?: Record<number, string>;
  title?: string;
  saveLabel?: string;
};

const initial = (cols: Column[]) => Object.fromEntries(cols.map((c) => [c.id, c.default_value ?? '']));

export function LineItemModal({ visible, columns, onClose, onSave, useInventory, initialValues, title = 'Add item', saveLabel = 'Add to invoice' }: Props) {
  const [values, setValues] = useState<Record<number, string>>(() => initial(columns));
  const [inventoryId, setInventoryId] = useState<number | undefined>();
  const [picking, setPicking] = useState(false);
  useEffect(() => { if (visible) { setValues(initialValues ?? initial(columns)); setInventoryId(undefined); } }, [visible, columns, initialValues]);

  // Same mapping the web form uses: columns are matched by their title.
  const fromInventory = (p: InventoryProduct) => {
    const byTitle = (re: RegExp) => columns.find((c) => re.test(c.input_title));
    const next: Record<number, string> = {};
    const set = (c: Column | undefined, v: string) => { if (c) next[c.id] = v; };
    set(byTitle(/^name of product$/i) ?? byTitle(/^(item|product)/i), p.name);
    set(byTitle(/^rate$/i), String(Number(p.price)));
    set(byTitle(/^gst$/i), String(Number(p.gst_percentage)));
    set(byTitle(/descri?p?tion|decription/i), p.description ?? '');
    setValues((s) => ({ ...s, ...next }));
    setInventoryId(p.id);
  };

  const calc = useMemo(
    () => calculateLine(columns.map((c) => ({ column: c, value: values[c.id] ?? '' })), columns),
    [columns, values],
  );

  const save = () => onSave({ values, inventoryProductId: inventoryId });

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.screen}>
        <View style={styles.top}>
          <Text style={styles.title}>{title}</Text>
          <TouchableOpacity onPress={onClose} hitSlop={10}><Ionicons name="close" size={26} color={Palette.text} /></TouchableOpacity>
        </View>
        <ScrollView contentContainerStyle={{ padding: 20 }} keyboardShouldPersistTaps="handled">
          {useInventory && (
            <TouchableOpacity style={styles.pick} onPress={() => setPicking(true)}>
              <Ionicons name="cube-outline" size={20} color={Palette.primary} />
              <Text style={styles.pickText}>{inventoryId ? 'Inventory item selected · change' : 'Pick from inventory'}</Text>
            </TouchableOpacity>
          )}
          {columns.map((c) => {
            const presets = c.presets ? c.presets.split(',').map((s) => s.trim()).filter(Boolean) : [];
            const numeric = c.is_calculable || c.input_title === 'GST';
            return (
              <View key={c.id} style={{ marginBottom: 16 }}>
                <Text style={styles.label}>{c.input_title}{c.formula ? `  (${c.formula})` : ''}</Text>
                <TextInput
                  style={styles.input}
                  value={values[c.id] ?? ''}
                  onChangeText={(v) => setValues((s) => ({ ...s, [c.id]: v }))}
                  keyboardType={numeric ? 'decimal-pad' : 'default'}
                  placeholder={c.input_title}
                  placeholderTextColor={Palette.textFaint}
                />
                {presets.length > 0 && (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }} contentContainerStyle={{ gap: 8 }}>
                    {presets.map((p) => (
                      <Chip key={p} label={p} active={values[c.id] === p} onPress={() => setValues((s) => ({ ...s, [c.id]: p }))} />
                    ))}
                  </ScrollView>
                )}
              </View>
            );
          })}
        </ScrollView>
        <View style={styles.footer}>
          <View>
            <Text style={styles.footLabel}>Line total</Text>
            <Text style={styles.footValue}>{money(calc.total_amount)}</Text>
          </View>
          <Button title={saveLabel} onPress={save} style={{ width: 170 }} />
        </View>
        <InventoryPicker visible={picking} onClose={() => setPicking(false)} onPick={(p) => { fromInventory(p); setPicking(false); }} />
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.white, paddingTop: 56 },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20 },
  title: { fontSize: 20, fontWeight: '800', color: Palette.text },
  label: { fontSize: 14, fontWeight: '700', color: Palette.label, marginBottom: 6 },
  input: { height: 50, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1.5, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  pick: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 14, borderRadius: 12, backgroundColor: '#eef2ff', marginBottom: 18 },
  pickText: { color: Palette.primary, fontWeight: '700', fontSize: 15 },
  footer: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: 20, paddingBottom: 32, borderTopWidth: 1, borderTopColor: Palette.border },
  footLabel: { fontSize: 12, color: Palette.textMuted },
  footValue: { fontSize: 20, fontWeight: '800', color: Palette.text },
});
