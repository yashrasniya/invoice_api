import React, { useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Centered, EmptyState, Fab } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { LABEL, listParties, PartyKind, PERMISSION } from '@/services/parties';

export function PartyList({ kind, topInset = true }: { kind: PartyKind; topInset?: boolean }) {
  const insets = useSafeAreaInsets();
  const canManage = useCan(PERMISSION[kind]);
  const [search, setSearch] = useState('');

  const q = useInfiniteQuery({
    queryKey: ['parties', kind, search],
    queryFn: ({ pageParam }) => listParties(kind, pageParam, search),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (last.next ? all.length + 1 : undefined),
  });
  const rows = q.data?.pages.flatMap((p) => p.results) ?? [];

  return (
    <View style={styles.screen}>
      <View style={[styles.header, { paddingTop: topInset ? insets.top + 12 : 12 }]}>
        {topInset && <Text style={styles.title}>{LABEL[kind]}s</Text>}
        <TextInput style={styles.search} placeholder={`Search ${kind}s`} placeholderTextColor={Palette.textFaint}
          value={search} onChangeText={setSearch} autoCapitalize="none" />
      </View>
      {q.isLoading ? <Centered /> : (
        <FlatList
          data={rows}
          keyExtractor={(r) => String(r.id)}
          contentContainerStyle={{ padding: 16, paddingBottom: 100, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching && !q.isFetchingNextPage} onRefresh={q.refetch} />}
          onEndReached={() => q.hasNextPage && !q.isFetchingNextPage && q.fetchNextPage()}
          ListEmptyComponent={q.error
            ? <EmptyState icon="alert-circle-outline" title={`Couldn't load ${kind}s`} hint={errorMessage(q.error)} />
            : <EmptyState icon="people-outline" title={`No ${kind}s yet`} hint={canManage ? 'Tap + to add one.' : undefined} />}
          ListFooterComponent={q.isFetchingNextPage ? <ActivityIndicator style={{ margin: 16 }} color={Palette.primary} /> : null}
          renderItem={({ item }) => (
            <TouchableOpacity style={styles.card} onPress={() => router.push(`/party/${kind}/${item.id}`)}>
              <View style={styles.avatar}><Text style={styles.avatarText}>{item.name.trim()[0]?.toUpperCase() ?? '?'}</Text></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.sub} numberOfLines={1}>
                  {[item.phone_number, item.gst_number].filter(Boolean).join(' · ') || 'No contact details'}
                </Text>
              </View>
              {item.total_billed != null && <Text style={styles.billed}>{money(item.total_billed)}</Text>}
              <Ionicons name="chevron-forward" size={18} color={Palette.textFaint} />
            </TouchableOpacity>
          )}
        />
      )}
      {canManage && <Fab label={`Add ${kind}`} onPress={() => router.push(`/party/${kind}/new`)} />}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  header: { paddingHorizontal: 16, paddingBottom: 12, backgroundColor: Palette.white, borderBottomWidth: 1, borderBottomColor: Palette.border },
  title: { fontSize: 26, fontWeight: '800', color: Palette.text, marginBottom: 12 },
  search: { height: 44, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: Palette.white, borderRadius: 16, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: Palette.border },
  avatar: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#eef2ff', alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: Palette.primary, fontWeight: '800', fontSize: 17 },
  name: { fontSize: 16, fontWeight: '700', color: Palette.text },
  sub: { fontSize: 13, color: Palette.textMuted, marginTop: 2 },
  billed: { fontSize: 14, fontWeight: '700', color: Palette.text },
});
