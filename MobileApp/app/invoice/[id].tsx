import React, { useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import * as Sharing from 'expo-sharing';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Centered, StatusBadge } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { summarizeLine } from '@/lib/line-display';
import { errorMessage } from '@/services/api';
import { reportFirstShare } from '@/services/onboarding';
import { deleteInvoice, downloadPdf, getInvoice, METHOD_LABEL, shareOnWhatsapp, updateInvoice } from '@/services/invoices';

export default function InvoiceDetailScreen() {
  const { id: raw } = useLocalSearchParams<{ id: string }>();
  const id = Number(raw);
  const qc = useQueryClient();
  const canUpdate = useCan('invoice.update');
  const canCreate = useCan('invoice.create');
  const canDelete = useCan('invoice.delete');
  const canWhatsapp = useCan('whatsapp.send');
  const [busy, setBusy] = useState<string | null>(null);

  const q = useQuery({ queryKey: ['invoice', id], queryFn: () => getInvoice(id) });
  const inv = q.data;

  const refreshLists = () => {
    qc.invalidateQueries({ queryKey: ['invoices'] });
    qc.invalidateQueries({ queryKey: ['dashboard'] });
  };

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try { await fn(); } catch (e) { Alert.alert('Something went wrong', errorMessage(e)); } finally { setBusy(null); }
  };

  const sharePdf = () => run('pdf', async () => {
    const uri = await downloadPdf(id);
    if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing is not available on this device.');
    await Sharing.shareAsync(uri, { mimeType: 'application/pdf', dialogTitle: `Invoice ${inv?.invoice_number ?? id}`, UTI: 'com.adobe.pdf' });
    reportFirstShare().catch(() => {}); // ticks the "Send it to a customer" step; best-effort
  });

  const whatsapp = () => {
    Alert.alert('Send on WhatsApp', `Send this invoice to ${inv?.receiver_name}?`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Send', onPress: () => run('wa', async () => { await shareOnWhatsapp(id); Alert.alert('Sent', 'Invoice sent on WhatsApp.'); }) },
    ]);
  };

  const markPaid = useMutation({
    mutationFn: () => updateInvoice(id, { payment_status: 'paid' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['invoice', id] }); refreshLists(); },
    onError: (e) => Alert.alert('Could not update', errorMessage(e)),
  });

  const remove = () => {
    Alert.alert('Delete invoice', 'This cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => run('del', async () => {
        await deleteInvoice(id);
        refreshLists();
        qc.removeQueries({ queryKey: ['invoice', id] });
        router.back();
      }) },
    ]);
  };

  if (q.isLoading) return <Centered />;
  if (!inv) return <Centered><Text style={{ color: Palette.danger }}>{errorMessage(q.error, 'Invoice not found')}</Text></Centered>;

  const purchase = inv.invoice_type === 'purchase';
  const partyName = purchase ? inv.vendor_name : inv.receiver_name;
  const taxable = Number(inv.total_final_amount || 0) - Number(inv.gst_final_amount || 0);

  return (
    <>
      <Stack.Screen options={{ title: inv.invoice_number ? `${purchase ? 'Bill' : 'Invoice'} #${inv.invoice_number}` : purchase ? 'Purchase bill' : 'Invoice' }} />
      <ScrollView style={styles.screen} contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        <View style={styles.card}>
          <View style={styles.rowBetween}>
            <Text style={styles.customer}>{partyName || (purchase ? 'No vendor' : 'No customer')}</Text>
            <StatusBadge status={inv.payment_status} />
          </View>
          {!!(purchase ? inv.vendor_gst_number : inv.receiver_gst_number) && (
            <Text style={styles.meta}>GSTIN {purchase ? inv.vendor_gst_number : inv.receiver_gst_number}</Text>
          )}
          <Text style={styles.meta}>
            {inv.date}{inv.payment_method ? ` · ${METHOD_LABEL[inv.payment_method]}` : ''}
          </Text>
        </View>

        <Text style={styles.section}>Items</Text>
        <View style={styles.card}>
          {inv.products.length === 0 && <Text style={styles.meta}>No items</Text>}
          {inv.products.map((p, i) => {
            const s = summarizeLine(p);
            return (
              <View key={p.id} style={[styles.line, i > 0 && styles.lineBorder]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineName}>{s.name}</Text>
                  {!!s.details && <Text style={styles.meta}>{s.details}</Text>}
                </View>
                <Text style={styles.lineAmt}>{money(p.total_amount)}</Text>
              </View>
            );
          })}
        </View>

        <View style={styles.card}>
          <View style={styles.rowBetween}><Text style={styles.meta}>Taxable value</Text><Text style={styles.val}>{money(taxable)}</Text></View>
          <View style={styles.rowBetween}><Text style={styles.meta}>GST</Text><Text style={styles.val}>{money(inv.gst_final_amount)}</Text></View>
          <View style={[styles.rowBetween, styles.totalRow]}><Text style={styles.totalLabel}>Total</Text><Text style={styles.total}>{money(inv.total_final_amount)}</Text></View>
        </View>

        <View style={{ gap: 10, marginTop: 8 }}>
          {!purchase && <Button title="Share PDF" onPress={sharePdf} loading={busy === 'pdf'} />}
          {canWhatsapp && !purchase && <Button title="Send on WhatsApp" variant="outline" onPress={whatsapp} loading={busy === 'wa'} />}
          {canUpdate && inv.payment_status !== 'paid' && (
            <Button title="Mark as paid" variant="outline" onPress={() => markPaid.mutate()} loading={markPaid.isPending} />
          )}
          {canUpdate && <Button title="Edit" variant="outline" onPress={() => router.push(`/invoice/edit/${id}`)} />}
          {canCreate && !purchase && <Button title="Duplicate" variant="outline" onPress={() => router.push(`/invoice/new?copy=${id}`)} />}
          {canDelete && <Button title="Delete" variant="danger" onPress={remove} loading={busy === 'del'} />}
        </View>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  card: { backgroundColor: Palette.white, borderRadius: 16, padding: 16, marginBottom: 12, borderWidth: 1, borderColor: Palette.border, gap: 6 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  customer: { fontSize: 20, fontWeight: '800', color: Palette.text, flex: 1, marginRight: 8 },
  meta: { fontSize: 13, color: Palette.textMuted },
  section: { fontSize: 13, fontWeight: '700', color: Palette.textMuted, textTransform: 'uppercase', marginVertical: 8, marginLeft: 4 },
  line: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 },
  lineBorder: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: Palette.border },
  lineName: { fontSize: 16, fontWeight: '600', color: Palette.text },
  lineAmt: { fontSize: 15, fontWeight: '700', color: Palette.text },
  val: { fontSize: 15, fontWeight: '600', color: Palette.text },
  totalRow: { borderTopWidth: 1, borderTopColor: Palette.border, paddingTop: 10, marginTop: 4 },
  totalLabel: { fontSize: 16, fontWeight: '800', color: Palette.text },
  total: { fontSize: 22, fontWeight: '800', color: Palette.primary },
});
