import React, { useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { router } from 'expo-router';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Centered, Chip, EmptyState, Fab, StatusBadge } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { InvoiceType, listInvoices, PaymentStatus, STATUS_LABEL } from '@/services/invoices';

const FILTERS: (PaymentStatus | '')[] = ['', 'unpaid', 'overdue', 'partially_paid', 'paid'];

type Props = {
  type: InvoiceType;
  title?: string;
  /** space for the status bar when the list is the top of a tab (no navigation header) */
  topInset?: number;
  /** rendered above the search box, scrolls away with nothing — used for summary cards */
  header?: React.ReactNode;
};

export function InvoiceList({ type, title, topInset = 0, header }: Props) {
  const purchase = type === 'purchase';
  const canCreate = useCan('invoice.create');
  const canView = useCan('invoice.view');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<PaymentStatus | ''>('');

  const q = useInfiniteQuery({
    queryKey: ['invoices', { type, search, status }],
    queryFn: ({ pageParam }) => listInvoices(pageParam, { type, search, payment_status: status }),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (last.next ? all.length + 1 : undefined),
    enabled: canView,
  });
  const rows = q.data?.pages.flatMap((p) => p.results) ?? [];

  const list = !canView ? (
    <EmptyState icon="lock-closed-outline" title="No access" hint="You don't have permission to view invoices." />
  ) : q.isLoading ? <Centered /> : (
    <FlatList
      data={rows}
      keyExtractor={(r) => String(r.id)}
      contentContainerStyle={{ padding: 16, paddingBottom: 100, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching && !q.isFetchingNextPage} onRefresh={() => { void q.refetch(); }} />}
      onEndReached={() => q.hasNextPage && !q.isFetchingNextPage && q.fetchNextPage()}
      onEndReachedThreshold={0.4}
      ListEmptyComponent={q.error
        ? <EmptyState icon="alert-circle-outline" title="Couldn't load invoices" hint={errorMessage(q.error)} />
        : <EmptyState icon="document-text-outline" title={purchase ? 'No purchase bills' : 'No invoices'}
            hint={search || status ? 'Try a different filter.' : purchase ? 'Scan a bill or tap + to add one.' : 'Tap + to create your first invoice.'} />}
      ListFooterComponent={q.isFetchingNextPage ? <ActivityIndicator style={{ margin: 16 }} color={Palette.primary} /> : undefined}
      renderItem={({ item }) => (
        <TouchableOpacity style={styles.card} onPress={() => router.push(`/invoice/${item.id}`)}>
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={styles.name} numberOfLines={1}>
              {(purchase ? item.vendor_name : item.receiver_name) || (purchase ? 'No vendor' : 'No customer')}
            </Text>
            <Text style={styles.sub}>{item.invoice_number ? `#${item.invoice_number}` : `${purchase ? 'Bill' : 'Invoice'} ${item.id}`} · {item.date}</Text>
          </View>
          <View style={{ alignItems: 'flex-end', gap: 6 }}>
            <Text style={styles.amount}>{money(item.total_final_amount)}</Text>
            <StatusBadge status={item.payment_status} />
          </View>
        </TouchableOpacity>
      )}
    />
  );

  return (
    <View style={styles.screen}>
      {header}
      <View style={[styles.header, { paddingTop: topInset + 12 }]}>
        {!!title && <Text style={styles.title}>{title}</Text>}
        <TextInput style={styles.search} placeholder={purchase ? 'Search bill number or vendor' : 'Search number or customer'}
          placeholderTextColor={Palette.textFaint} value={search} onChangeText={setSearch} autoCapitalize="none" />
        <FlatList
          horizontal showsHorizontalScrollIndicator={false} data={FILTERS} keyExtractor={(f) => f || 'all'}
          contentContainerStyle={{ gap: 8, paddingTop: 12 }}
          renderItem={({ item }) => (
            <Chip label={item ? STATUS_LABEL[item] : 'All'} active={status === item} onPress={() => setStatus(item)} />
          )}
        />
      </View>
      {list}
      {canCreate && <Fab label={purchase ? 'Add purchase bill' : 'Create invoice'} onPress={() => router.push(purchase ? '/invoice/new?type=purchase' : '/invoice/new')} />}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  header: { paddingHorizontal: 16, paddingBottom: 12, backgroundColor: Palette.white, borderBottomWidth: 1, borderBottomColor: Palette.border },
  title: { fontSize: 26, fontWeight: '800', color: Palette.text, marginBottom: 12 },
  search: { height: 44, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: Palette.white, borderRadius: 16, padding: 16, marginBottom: 10, borderWidth: 1, borderColor: Palette.border },
  name: { fontSize: 16, fontWeight: '700', color: Palette.text },
  sub: { fontSize: 13, color: Palette.textMuted },
  amount: { fontSize: 16, fontWeight: '800', color: Palette.text },
});
