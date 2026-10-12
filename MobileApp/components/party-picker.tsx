import React, { useState } from 'react';
import { FlatList, Modal, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Palette } from '@/constants/theme';
import { listParties, Party, PartyKind, PERMISSION } from '@/services/parties';
import { Centered, EmptyState } from '@/components/ui/bits';
import { useCan } from '@/hooks/use-access';

type Props = {
  kind: PartyKind;
  visible: boolean;
  onClose: () => void;
  onPick: (p: Party) => void;
};

export function PartyPicker({ kind, visible, onClose, onPick }: Props) {
  const [search, setSearch] = useState('');
  const canAdd = useCan(PERMISSION[kind]);
  const q = useInfiniteQuery({
    queryKey: ['party-picker', kind, search],
    queryFn: ({ pageParam }) => listParties(kind, pageParam, search),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (last.next ? all.length + 1 : undefined),
    enabled: visible,
  });
  const rows = q.data?.pages.flatMap((p) => p.results) ?? [];

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.screen}>
        <View style={styles.top}>
          <Text style={styles.title}>Select {kind}</Text>
          <TouchableOpacity onPress={onClose} hitSlop={10}><Ionicons name="close" size={26} color={Palette.text} /></TouchableOpacity>
        </View>
        <TextInput style={styles.search} placeholder={`Search ${kind}s`} placeholderTextColor={Palette.textFaint}
          value={search} onChangeText={setSearch} autoCapitalize="none" />
        {canAdd && (
          <TouchableOpacity style={styles.add} onPress={() => { onClose(); router.push(`/party/${kind}/new`); }}>
            <Ionicons name="add-circle-outline" size={20} color={Palette.primary} />
            <Text style={styles.addText}>Add new {kind}</Text>
          </TouchableOpacity>
        )}
        {q.isLoading ? <Centered /> : (
          <FlatList
            data={rows}
            keyExtractor={(r) => String(r.id)}
            keyboardShouldPersistTaps="handled"
            onEndReached={() => q.hasNextPage && !q.isFetchingNextPage && q.fetchNextPage()}
            ListEmptyComponent={<EmptyState icon="people-outline" title={`No ${kind}s found`} />}
            renderItem={({ item }) => (
              <TouchableOpacity style={styles.row} onPress={() => { onPick(item); onClose(); }}>
                <Text style={styles.name}>{item.name}</Text>
                {!!(item.gst_number || item.phone_number) && (
                  <Text style={styles.sub}>{[item.gst_number, item.phone_number].filter(Boolean).join(' · ')}</Text>
                )}
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
  search: { marginHorizontal: 20, height: 46, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  add: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 20, paddingVertical: 14 },
  addText: { color: Palette.primary, fontWeight: '700', fontSize: 15 },
  row: { paddingHorizontal: 20, paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: Palette.border },
  name: { fontSize: 16, fontWeight: '600', color: Palette.text },
  sub: { fontSize: 13, color: Palette.textMuted, marginTop: 2 },
});
