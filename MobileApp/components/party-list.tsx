import React, { useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Centered, EmptyState, Fab } from '@/components/ui/bits';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { useCan } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { LABEL, listParties, PartyKind, PERMISSION } from '@/services/parties';

export function PartyList({ kind, topInset = true }: { kind: PartyKind; topInset?: boolean }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
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
        <TextInput style={styles.search} placeholder={`Search ${kind}s`} placeholderTextColor={theme.textFaint}
          value={search} onChangeText={setSearch} autoCapitalize="none" />
      </View>
      {q.isLoading ? <Centered /> : (
        <FlatList
          data={rows}
          keyExtractor={(r) => String(r.id)}
          contentContainerStyle={{ padding: 16, paddingBottom: 100, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching && !q.isFetchingNextPage} onRefresh={() => { void q.refetch(); }} />}
          onEndReached={() => q.hasNextPage && !q.isFetchingNextPage && q.fetchNextPage()}
          ListEmptyComponent={q.error
            ? <EmptyState icon="alert-circle-outline" title={`Couldn't load ${kind}s`} hint={errorMessage(q.error)} />
            : <EmptyState icon="people-outline" title={`No ${kind}s yet`} hint={canManage ? 'Tap + to add one.' : undefined} />}
          ListFooterComponent={q.isFetchingNextPage ? <ActivityIndicator style={{ margin: 16 }} color={theme.primary} /> : undefined}
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
              <Ionicons name="chevron-forward" size={18} color={theme.textFaint} />
            </TouchableOpacity>
          )}
        />
      )}
      {canManage && <Fab label={`Add ${kind}`} onPress={() => router.push(`/party/${kind}/new`)} />}
    </View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.background },
  header: { paddingHorizontal: 16, paddingBottom: 12, backgroundColor: t.surface, borderBottomWidth: 1, borderBottomColor: t.border },
  title: { fontSize: 26, fontWeight: '800', color: t.text, marginBottom: 12 },
  search: { height: 44, borderRadius: 12, backgroundColor: t.isDark ? t.surfaceRaised : t.background, borderWidth: 1, borderColor: t.border, paddingHorizontal: 14, fontSize: 16, color: t.text },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: t.surface, borderRadius: 16, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: t.border },
  avatar: { width: 42, height: 42, borderRadius: 21, backgroundColor: t.primarySoft, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: t.primary, fontWeight: '800', fontSize: 17 },
  name: { fontSize: 16, fontWeight: '700', color: t.text },
  sub: { fontSize: 13, color: t.textMuted, marginTop: 2 },
  billed: { fontSize: 14, fontWeight: '700', color: t.text },
});
