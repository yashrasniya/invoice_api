import React, { useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack, router } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Centered, Chip, EmptyState, Fab } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { isLowStock, listInventory } from '@/services/inventory';

export default function InventoryScreen() {
  const hasFeature = useFeature('inventory');
  const canManage = useCan('inventory.manage');
  const [search, setSearch] = useState('');
  const [lowOnly, setLowOnly] = useState(false);

  const allowed = hasFeature && canManage;
  const q = useQuery({ queryKey: ['inventory', search], queryFn: () => listInventory(search), enabled: allowed });
  const rows = (q.data ?? []).filter((p) => !lowOnly || isLowStock(p));

  if (!allowed) {
    return (
      <>
        <Stack.Screen options={{ title: 'Inventory' }} />
        <EmptyState
          icon="lock-closed-outline"
          title={hasFeature ? 'No access' : 'Inventory is not in your plan'}
          hint={hasFeature ? "You don't have permission to manage inventory." : 'Upgrade your plan on the web to use inventory.'}
        />
      </>
    );
  }

  return (
    <View style={styles.screen}>
      <Stack.Screen
        options={{
          title: 'Inventory',
          headerRight: () => (
            <View style={{ flexDirection: 'row', gap: 18 }}>
              <TouchableOpacity onPress={() => router.push('/inventory/scan')} hitSlop={8} accessibilityLabel="Scan barcode">
                <Ionicons name="barcode-outline" size={24} color={Palette.primary} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => router.push('/inventory/categories')} hitSlop={8} accessibilityLabel="Categories">
                <Ionicons name="pricetags-outline" size={22} color={Palette.primary} />
              </TouchableOpacity>
            </View>
          ),
        }}
      />
      <View style={styles.header}>
        <TextInput style={styles.search} placeholder="Search name or SKU" placeholderTextColor={Palette.textFaint}
          value={search} onChangeText={setSearch} autoCapitalize="none" />
        <View style={{ flexDirection: 'row', gap: 8, marginTop: 10 }}>
          <Chip label="All" active={!lowOnly} onPress={() => setLowOnly(false)} />
          <Chip label="Low stock" active={lowOnly} onPress={() => setLowOnly(true)} />
        </View>
      </View>

      {q.isLoading ? <Centered /> : (
        <FlatList
          data={rows}
          keyExtractor={(p) => String(p.id)}
          contentContainerStyle={{ padding: 16, paddingBottom: 100, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} />}
          ListEmptyComponent={q.error
            ? <EmptyState icon="alert-circle-outline" title="Couldn't load inventory" hint={errorMessage(q.error)} />
            : <EmptyState icon="cube-outline" title={lowOnly ? 'Nothing is low on stock' : 'No products yet'} hint={lowOnly ? undefined : 'Tap + or scan a barcode to add one.'} />}
          renderItem={({ item }) => {
            const low = isLowStock(item);
            return (
              <TouchableOpacity style={styles.card} onPress={() => router.push(`/inventory/${item.id}`)}>
                <View style={{ flex: 1, gap: 3 }}>
                  <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
                  <Text style={styles.sub} numberOfLines={1}>{item.sku}{item.category_name ? ` · ${item.category_name}` : ''}</Text>
                  <Text style={styles.sub}>{money(item.price)} · GST {Number(item.gst_percentage)}%</Text>
                </View>
                <View style={[styles.stock, low && styles.stockLow]}>
                  <Text style={[styles.stockNum, low && { color: Palette.danger }]}>{item.current_stock}</Text>
                  <Text style={[styles.stockLabel, low && { color: Palette.danger }]}>{low ? 'low' : 'in stock'}</Text>
                </View>
              </TouchableOpacity>
            );
          }}
        />
      )}
      <Fab label="Add product" onPress={() => router.push('/inventory/new')} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  header: { padding: 16, backgroundColor: Palette.white, borderBottomWidth: 1, borderBottomColor: Palette.border },
  search: { height: 44, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: Palette.white, borderRadius: 16, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: Palette.border },
  name: { fontSize: 16, fontWeight: '700', color: Palette.text },
  sub: { fontSize: 13, color: Palette.textMuted },
  stock: { minWidth: 64, alignItems: 'center', paddingVertical: 8, paddingHorizontal: 10, borderRadius: 12, backgroundColor: '#f0fdf4' },
  stockLow: { backgroundColor: '#fef2f2' },
  stockNum: { fontSize: 18, fontWeight: '800', color: Palette.success },
  stockLabel: { fontSize: 11, fontWeight: '600', color: Palette.success },
});
