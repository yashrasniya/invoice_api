import React, { useState } from 'react';
import { FlatList, Modal, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { money } from '@/lib/invoice-calc';
import { InventoryProduct, listInventory } from '@/services/inventory';

type Props = { visible: boolean; onClose: () => void; onPick: (p: InventoryProduct) => void };

export function InventoryPicker({ visible, onClose, onPick }: Props) {
  const [search, setSearch] = useState('');
  const q = useQuery({ queryKey: ['inventory-picker', search], queryFn: () => listInventory(search), enabled: visible });

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.screen}>
        <View style={styles.top}>
          <Text style={styles.title}>Inventory</Text>
          <TouchableOpacity onPress={onClose} hitSlop={10}><Ionicons name="close" size={26} color={Palette.text} /></TouchableOpacity>
        </View>
        <TextInput style={styles.search} placeholder="Search name or SKU" placeholderTextColor={Palette.textFaint}
          value={search} onChangeText={setSearch} autoCapitalize="none" />
        {q.isLoading ? <Centered /> : (
          <FlatList
            data={q.data ?? []}
            keyExtractor={(p) => String(p.id)}
            keyboardShouldPersistTaps="handled"
            ListEmptyComponent={<EmptyState icon="cube-outline" title="No products found" />}
            renderItem={({ item }) => (
              <TouchableOpacity style={styles.row} onPress={() => onPick(item)}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{item.name}</Text>
                  <Text style={styles.sub}>{item.sku} · {money(item.price)} · GST {Number(item.gst_percentage)}%</Text>
                </View>
                <Text style={[styles.stock, item.current_stock <= 0 && { color: Palette.danger }]}>{item.current_stock} left</Text>
              </TouchableOpacity>
            )}
          />
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.white, paddingTop: 56 },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20, marginBottom: 12 },
  title: { fontSize: 20, fontWeight: '800', color: Palette.text },
  search: { marginHorizontal: 20, marginBottom: 8, height: 46, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 20, paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: Palette.border },
  name: { fontSize: 16, fontWeight: '600', color: Palette.text },
  sub: { fontSize: 13, color: Palette.textMuted, marginTop: 2 },
  stock: { fontSize: 13, fontWeight: '700', color: Palette.success },
});
