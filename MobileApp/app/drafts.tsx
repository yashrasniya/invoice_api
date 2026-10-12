import React, { useState } from 'react';
import { Alert, FlatList, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { money } from '@/lib/invoice-calc';
import { errorMessage, isOfflineError } from '@/services/api';
import { createInvoice, totalsFor } from '@/services/invoices';
import { Draft, useDrafts, useMyDrafts } from '@/store/drafts';

export default function DraftsScreen() {
  const qc = useQueryClient();
  const drafts = useMyDrafts();
  const remove = useDrafts((s) => s.remove);
  const [sending, setSending] = useState<string | null>(null);

  const send = async (d: Draft) => {
    setSending(d.id);
    try {
      await createInvoice(d.input, d.lines, d.columns, d.type);
      remove(d.id);
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
    } catch (e) {
      Alert.alert(isOfflineError(e) ? 'Still offline' : 'Could not send', isOfflineError(e) ? 'Connect to the internet and try again.' : errorMessage(e));
    } finally {
      setSending(null);
    }
  };

  const discard = (d: Draft) =>
    Alert.alert('Discard draft', 'This draft will be deleted from your phone.', [
      { text: 'Cancel', style: 'cancel' }, { text: 'Discard', style: 'destructive', onPress: () => remove(d.id) },
    ]);

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: 'Drafts' }} />
      <FlatList
        data={[...drafts].reverse()}
        keyExtractor={(d) => d.id}
        contentContainerStyle={{ padding: 16, flexGrow: 1 }}
        ListEmptyComponent={<EmptyState icon="cloud-done-outline" title="No drafts" hint="Invoices you finish without a connection are saved here until they can be sent." />}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.name}>{item.partyName}</Text>
            <Text style={styles.meta}>
              {item.type === 'purchase' ? 'Purchase bill' : 'Invoice'} · {item.input.date} · {item.lines.length} item{item.lines.length === 1 ? '' : 's'} · {money(totalsFor(item.lines, item.columns).total)}
            </Text>
            <Text style={styles.meta}>Saved {new Date(item.createdAt).toLocaleString()}</Text>
            <View style={styles.row}>
              <Button title="Send now" onPress={() => send(item)} loading={sending === item.id} style={{ flex: 1, height: 46 }} />
              <Button title="Discard" variant="danger" onPress={() => discard(item)} disabled={sending === item.id} style={{ flex: 1, height: 46 }} />
            </View>
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  card: { backgroundColor: Palette.white, borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: Palette.border, gap: 4 },
  name: { fontSize: 16, fontWeight: '700', color: Palette.text },
  meta: { fontSize: 13, color: Palette.textMuted },
  row: { flexDirection: 'row', gap: 10, marginTop: 10 },
});
