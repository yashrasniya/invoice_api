import React, { useEffect, useState } from 'react';
import { Alert, KeyboardAvoidingView, Modal, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Centered, Chip } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import {
  addMovement, deleteInventoryProduct, getInventoryProduct, isLowStock, listCategories, listMovements,
  ProductInput, saveInventoryProduct,
} from '@/services/inventory';

const EMPTY: ProductInput = {
  sku: '', name: '', description: '', category: null, price: '', gst_percentage: '18', reorder_level: '10', current_stock: '0',
};

export default function InventoryProductScreen() {
  const { id: rawId, sku } = useLocalSearchParams<{ id: string; sku?: string }>();
  const isNew = rawId === 'new';
  const id = isNew ? undefined : Number(rawId);
  const qc = useQueryClient();

  const [form, setForm] = useState<ProductInput>({ ...EMPTY, sku: sku ?? '' });
  const [saving, setSaving] = useState(false);
  const [adjust, setAdjust] = useState<null | 'IN' | 'OUT'>(null);
  const set = (k: keyof ProductInput) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const product = useQuery({ queryKey: ['inventory-product', id], queryFn: () => getInventoryProduct(id!), enabled: !isNew });
  const categories = useQuery({ queryKey: ['inventory-categories'], queryFn: listCategories });
  const movements = useQuery({ queryKey: ['inventory-movements', id], queryFn: () => listMovements(id!), enabled: !isNew });

  useEffect(() => {
    const p = product.data;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync local form state from fetched server data / a prop change
    if (p) setForm({
      sku: p.sku, name: p.name, description: p.description ?? '', category: p.category,
      price: String(p.price), gst_percentage: String(Number(p.gst_percentage)), reorder_level: String(p.reorder_level),
    });
  }, [product.data]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['inventory'] });
    qc.invalidateQueries({ queryKey: ['inventory-product', id] });
    qc.invalidateQueries({ queryKey: ['inventory-movements', id] });
    qc.invalidateQueries({ queryKey: ['inventory-picker'] });
  };

  const save = async () => {
    if (!form.sku.trim() || !form.name.trim()) return Alert.alert('Missing details', 'SKU and name are required.');
    const price = Number(form.price);
    if (!form.price.trim() || !Number.isFinite(price) || price < 0) return Alert.alert('Invalid price', 'Enter a valid price.');
    const gst = Number(form.gst_percentage || 0);
    if (!Number.isFinite(gst) || gst < 0 || gst > 100) return Alert.alert('Invalid GST', 'GST must be between 0 and 100.');
    setSaving(true);
    try {
      await saveInventoryProduct(form, id);
      refresh();
      router.back();
    } catch (e) {
      Alert.alert('Could not save', errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = () => Alert.alert('Delete product', 'This cannot be undone.', [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Delete', style: 'destructive', onPress: async () => {
      try { await deleteInventoryProduct(id!); refresh(); router.back(); }
      catch (e) { Alert.alert('Could not delete', errorMessage(e)); }
    } },
  ]);

  if (!isNew && product.isLoading) return <Centered />;
  const p = product.data;

  return (
    <>
      <Stack.Screen options={{ title: isNew ? 'New product' : p?.name ?? 'Product' }} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, backgroundColor: Palette.white }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          {p && (
            <View style={[styles.stockCard, isLowStock(p) && { backgroundColor: '#fef2f2' }]}>
              <Text style={styles.stockLabel}>Current stock</Text>
              <Text style={[styles.stockNum, isLowStock(p) && { color: Palette.danger }]}>{p.current_stock}</Text>
              {isLowStock(p) && <Text style={{ color: Palette.danger, fontWeight: '600' }}>At or below reorder level ({p.reorder_level})</Text>}
              <View style={{ flexDirection: 'row', gap: 10, marginTop: 12 }}>
                <Button title="Stock in" variant="outline" onPress={() => setAdjust('IN')} style={{ flex: 1, height: 46 }} />
                <Button title="Stock out" variant="outline" onPress={() => setAdjust('OUT')} style={{ flex: 1, height: 46 }} />
              </View>
            </View>
          )}

          <Field label="SKU / barcode" value={form.sku} onChangeText={set('sku')} autoCapitalize="characters" maxLength={100} />
          <Field label="Name" value={form.name} onChangeText={set('name')} />
          <Field label="Description" value={form.description} onChangeText={set('description')} multiline />

          <Text style={styles.label}>Category</Text>
          <View style={styles.chips}>
            <Chip label="None" active={form.category == null} onPress={() => setForm((f) => ({ ...f, category: null }))} />
            {(categories.data ?? []).map((c) => (
              <Chip key={c.id} label={c.name} active={form.category === c.id} onPress={() => setForm((f) => ({ ...f, category: c.id }))} />
            ))}
          </View>

          <View style={[styles.row, { marginTop: 18 }]}>
            <View style={{ flex: 1 }}><Field label="Price (₹)" value={form.price} onChangeText={set('price')} keyboardType="decimal-pad" /></View>
            <View style={{ flex: 1 }}><Field label="GST %" value={form.gst_percentage} onChangeText={set('gst_percentage')} keyboardType="decimal-pad" /></View>
          </View>
          <View style={styles.row}>
            {isNew && <View style={{ flex: 1 }}><Field label="Opening stock" value={form.current_stock ?? ''} onChangeText={set('current_stock')} keyboardType="number-pad" /></View>}
            <View style={{ flex: 1 }}><Field label="Reorder level" value={form.reorder_level} onChangeText={set('reorder_level')} keyboardType="number-pad" /></View>
          </View>

          <Button title={isNew ? 'Add product' : 'Save changes'} onPress={save} loading={saving} />
          {!isNew && <Button title="Delete product" variant="danger" onPress={remove} style={{ marginTop: 12 }} />}

          {!isNew && (
            <>
              <Text style={styles.section}>Stock history</Text>
              {(movements.data ?? []).length === 0 && <Text style={styles.empty}>No movements yet.</Text>}
              {(movements.data ?? []).slice(0, 30).map((m) => (
                <View key={m.id} style={styles.move}>
                  <Text style={[styles.moveQty, { color: m.movement_type === 'IN' ? Palette.success : Palette.danger }]}>
                    {m.movement_type === 'IN' ? '+' : '−'}{m.quantity}
                  </Text>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.moveNote} numberOfLines={2}>{m.notes || (m.movement_type === 'IN' ? 'Stock in' : 'Stock out')}</Text>
                    <Text style={styles.moveDate}>{new Date(m.date).toLocaleString()}</Text>
                  </View>
                </View>
              ))}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      {!!adjust && p && (
        <AdjustModal
          type={adjust}
          productName={p.name}
          onClose={() => setAdjust(null)}
          onSubmit={async (qty, notes) => {
            await addMovement({ product: p.id, quantity: qty, movement_type: adjust, notes });
            refresh();
            setAdjust(null);
          }}
        />
      )}
    </>
  );
}

function AdjustModal({ type, productName, onClose, onSubmit }: {
  type: 'IN' | 'OUT'; productName: string; onClose: () => void; onSubmit: (qty: number, notes: string) => Promise<void>;
}) {
  const [qty, setQty] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const go = async () => {
    const n = Number(qty);
    if (!Number.isInteger(n) || n <= 0) return Alert.alert('Invalid quantity', 'Enter a whole number greater than 0.');
    setBusy(true);
    try { await onSubmit(n, notes.trim()); } catch (e) { Alert.alert('Could not update stock', errorMessage(e)); setBusy(false); }
  };

  return (
    <Modal transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>{type === 'IN' ? 'Stock in' : 'Stock out'} · {productName}</Text>
            <Field label="Quantity" value={qty} onChangeText={setQty} keyboardType="number-pad" autoFocus />
            <Field label="Note (optional)" value={notes} onChangeText={setNotes} />
            <Button title="Update stock" onPress={go} loading={busy} />
            <TouchableOpacity onPress={onClose} style={{ alignItems: 'center', padding: 14 }}>
              <Text style={{ color: Palette.textMuted, fontWeight: '600' }}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 20, paddingBottom: 48 },
  stockCard: { backgroundColor: '#f0fdf4', borderRadius: 16, padding: 16, marginBottom: 20, alignItems: 'center' },
  stockLabel: { fontSize: 13, color: Palette.textMuted, fontWeight: '600' },
  stockNum: { fontSize: 40, fontWeight: '800', color: Palette.success },
  label: { fontSize: 14, fontWeight: '700', color: Palette.label, marginBottom: 8, marginLeft: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  row: { flexDirection: 'row', gap: 12 },
  section: { fontSize: 18, fontWeight: '800', color: Palette.text, marginTop: 28, marginBottom: 8 },
  empty: { color: Palette.textMuted },
  move: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: Palette.border },
  moveQty: { fontSize: 18, fontWeight: '800', width: 56 },
  moveNote: { fontSize: 14, color: Palette.text },
  moveDate: { fontSize: 12, color: Palette.textMuted, marginTop: 2 },
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.4)' },
  sheet: { backgroundColor: Palette.white, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 24, paddingBottom: 32 },
  sheetTitle: { fontSize: 18, fontWeight: '800', color: Palette.text, marginBottom: 18 },
});
