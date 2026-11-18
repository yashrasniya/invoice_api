import React, { useState } from 'react';
import { Alert, FlatList, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Button } from '@/components/ui/button';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { errorMessage } from '@/services/api';
import { createCategory, deleteCategory, listCategories } from '@/services/inventory';

export default function CategoriesScreen() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
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
        <TextInput style={styles.input} placeholder="New category name" placeholderTextColor={theme.textFaint}
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
                <Ionicons name="trash-outline" size={20} color={theme.danger} />
              </TouchableOpacity>
            </View>
          )}
        />
      )}
    </View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.background },
  add: { flexDirection: 'row', gap: 10, padding: 16, backgroundColor: t.surface, borderBottomWidth: 1, borderBottomColor: t.border },
  input: { flex: 1, height: 48, borderRadius: 12, backgroundColor: t.isDark ? t.surfaceRaised : t.background, borderWidth: 1, borderColor: t.border, paddingHorizontal: 14, fontSize: 16, color: t.text },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: t.surface, borderRadius: 14, padding: 16, marginBottom: 8, borderWidth: 1, borderColor: t.border },
  name: { fontSize: 16, fontWeight: '600', color: t.text },
});
