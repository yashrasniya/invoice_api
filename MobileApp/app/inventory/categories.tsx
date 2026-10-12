import React, { useState } from 'react';
import { Alert, FlatList, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Button } from '@/components/ui/button';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import { createCategory, deleteCategory, listCategories } from '@/services/inventory';

export default function CategoriesScreen() {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const q = useQuery({ queryKey: ['inventory-categories'], queryFn: listCategories });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['inventory-categories'] });
    qc.invalidateQueries({ queryKey: ['inventory'] });
  };

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try { await createCategory(name); setName(''); refresh(); }
    catch (e) { Alert.alert('Could not add category', errorMessage(e)); }
    finally { setBusy(false); }
  };

  const remove = (id: number, label: string) => Alert.alert('Delete category', `Delete "${label}"? Products keep existing but lose this category.`, [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Delete', style: 'destructive', onPress: async () => {
      try { await deleteCategory(id); refresh(); } catch (e) { Alert.alert('Could not delete', errorMessage(e)); }
    } },
  ]);

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: 'Categories' }} />
      <View style={styles.add}>
        <TextInput style={styles.input} placeholder="New category name" placeholderTextColor={Palette.textFaint}
          value={name} onChangeText={setName} onSubmitEditing={add} returnKeyType="done" />
        <Button title="Add" onPress={add} loading={busy} style={{ width: 90, height: 48 }} />
      </View>
      {q.isLoading ? <Centered /> : (
        <FlatList
          data={q.data ?? []}
          keyExtractor={(c) => String(c.id)}
          contentContainerStyle={{ padding: 16, flexGrow: 1 }}
          ListEmptyComponent={<EmptyState icon="pricetags-outline" title="No categories yet" />}
          renderItem={({ item }) => (
            <View style={styles.row}>
              <Text style={styles.name}>{item.name}</Text>
              <TouchableOpacity hitSlop={10} onPress={() => remove(item.id, item.name)}>
                <Ionicons name="trash-outline" size={20} color={Palette.danger} />
              </TouchableOpacity>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  add: { flexDirection: 'row', gap: 10, padding: 16, backgroundColor: Palette.white, borderBottomWidth: 1, borderBottomColor: Palette.border },
  input: { flex: 1, height: 48, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: Palette.white, borderRadius: 14, padding: 16, marginBottom: 8, borderWidth: 1, borderColor: Palette.border },
  name: { fontSize: 16, fontWeight: '600', color: Palette.text },
});
