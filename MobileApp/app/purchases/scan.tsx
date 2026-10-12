import React, { useState } from 'react';
import { Alert, FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack, router } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { BillFile, fetchOcrJobs, OcrJob, refreshOcrJob, uploadBill } from '@/services/purchases';

const STATE_STYLE = {
  completed: { bg: '#dcfce7', fg: '#166534', label: 'Done' },
  processing: { bg: '#fef3c7', fg: '#92400e', label: 'Reading…' },
  failed: { bg: '#fee2e2', fg: '#991b1b', label: 'Failed' },
} as const;

const stamp = () => new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14);

function Action({ icon, label, onPress, disabled }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void; disabled: boolean }) {
  return (
    <TouchableOpacity style={[styles.action, disabled && { opacity: 0.5 }]} disabled={disabled} onPress={onPress}
      accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={24} color={Palette.primary} />
      <Text style={styles.actionText}>{label}</Text>
    </TouchableOpacity>
  );
}

export default function ScanBillScreen() {
  const qc = useQueryClient();
  const hasFeature = useFeature('purchases_invoice');
  const canCreate = useCan('invoice.create');
  const [refreshing, setRefreshing] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ['ocr-jobs'],
    queryFn: fetchOcrJobs,
    enabled: hasFeature,
    // keep polling while anything is still being read
    refetchInterval: (query) => (query.state.data?.counts.processing ? 8000 : false),
  });
  const usage = q.data?.usage;
  const limit = usage?.monthly_limit;
  const blocked =
    !!usage && ((typeof limit === 'number' && limit > 0 && usage.this_month >= limit) || usage.today >= usage.daily_limit);

  const upload = useMutation({
    mutationFn: (f: BillFile) => uploadBill(f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ocr-jobs'] });
      Alert.alert('Uploaded', 'Your bill is being read. This usually takes under a minute.');
    },
    onError: (e) => Alert.alert('Upload failed', errorMessage(e)),
  });

  const actionsDisabled = blocked || !canCreate || upload.isPending;

  const fromCamera = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) return Alert.alert('Camera needed', 'Allow camera access in Settings to photograph bills.');
    const res = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.7 });
    const a = res.assets?.[0];
    if (!res.canceled && a) upload.mutate({ uri: a.uri, name: `bill-${stamp()}.jpg`, mimeType: a.mimeType ?? 'image/jpeg' });
  };

  const fromLibrary = async () => {
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7 });
    const a = res.assets?.[0];
    if (!res.canceled && a) upload.mutate({ uri: a.uri, name: a.fileName ?? `bill-${stamp()}.jpg`, mimeType: a.mimeType ?? 'image/jpeg' });
  };

  const fromFile = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: ['application/pdf', 'image/*'], copyToCacheDirectory: true });
    const a = res.assets?.[0];
    if (!res.canceled && a) upload.mutate({ uri: a.uri, name: a.name, mimeType: a.mimeType ?? 'application/pdf' });
  };

  const refreshJob = async (job: OcrJob) => {
    if (!job.job_id) return;
    setRefreshing(job.job_id);
    try { await refreshOcrJob(job.job_id); await q.refetch(); }
    catch (e) { Alert.alert('Could not check status', errorMessage(e)); }
    finally { setRefreshing(null); }
  };

  if (!hasFeature) {
    return (
      <>
        <Stack.Screen options={{ title: 'Scan bills' }} />
        <EmptyState icon="lock-closed-outline" title="Bill scanning is not in your plan" hint="Upgrade your plan on the web to scan purchase bills." />
      </>
    );
  }

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: 'Scan bills' }} />
      {q.isLoading ? <Centered /> : (
        <FlatList
          data={q.data?.jobs ?? []}
          keyExtractor={(j) => String(j.id)}
          contentContainerStyle={{ padding: 16, paddingBottom: 40, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { void q.refetch(); }} />}
          ListHeaderComponent={
            <View style={{ marginBottom: 12 }}>
              <View style={styles.actions}>
                <Action icon="camera-outline" label="Take photo" onPress={fromCamera} disabled={actionsDisabled} />
                <Action icon="image-outline" label="Photo library" onPress={fromLibrary} disabled={actionsDisabled} />
                <Action icon="document-outline" label="PDF / file" onPress={fromFile} disabled={actionsDisabled} />
              </View>
              {upload.isPending && <Text style={styles.uploading}>Uploading…</Text>}
              {!!usage && (
                <Text style={styles.usage}>
                  {usage.this_month}{typeof limit === 'number' ? ` of ${limit}` : ''} scans this month · {usage.today}/{usage.daily_limit} today
                  {blocked ? ' — limit reached' : ''}
                </Text>
              )}
              {!canCreate && <Text style={styles.usage}>You don&apos;t have permission to add bills.</Text>}
              <Text style={styles.section}>Recent scans</Text>
            </View>
          }
          ListEmptyComponent={q.error
            ? <EmptyState icon="alert-circle-outline" title="Couldn't load scans" hint={errorMessage(q.error)} />
            : <EmptyState icon="scan-outline" title="No scans yet" hint="Photograph a supplier bill and we'll read the details for you." />}
          renderItem={({ item }) => {
            const st = STATE_STYLE[item.state];
            const x = item.extracted;
            return (
              <View style={styles.card}>
                <View style={styles.rowBetween}>
                  <Text style={styles.file} numberOfLines={1}>{x.vendor_name || item.file_name.replace(/^[0-9a-f-]{36}_/, '')}</Text>
                  <View style={[styles.badge, { backgroundColor: st.bg }]}><Text style={[styles.badgeText, { color: st.fg }]}>{st.label}</Text></View>
                </View>
                {item.state === 'completed' && (
                  <Text style={styles.meta}>
                    {[x.invoice_number ? `#${x.invoice_number}` : null, x.date, x.total_amount != null ? money(x.total_amount) : null].filter(Boolean).join(' · ') || 'Extracted'}
                  </Text>
                )}
                <Text style={styles.meta}>{new Date(item.created_at).toLocaleString()}</Text>
                <View style={styles.rowBetween}>
                  {item.state === 'completed' ? (
                    <TouchableOpacity onPress={() => router.push('/purchases')}>
                      <Text style={styles.link}>Review in purchase bills →</Text>
                    </TouchableOpacity>
                  ) : <View />}
                  {item.state === 'processing' && !!item.job_id && (
                    <TouchableOpacity onPress={() => refreshJob(item)} disabled={refreshing === item.job_id}>
                      <Text style={styles.link}>{refreshing === item.job_id ? 'Checking…' : 'Check status'}</Text>
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            );
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  actions: { flexDirection: 'row', gap: 10 },
  action: { flex: 1, alignItems: 'center', gap: 6, backgroundColor: Palette.white, borderRadius: 14, paddingVertical: 16, borderWidth: 1, borderColor: Palette.border },
  actionText: { fontSize: 13, fontWeight: '700', color: Palette.text },
  uploading: { textAlign: 'center', color: Palette.primary, fontWeight: '600', marginTop: 10 },
  usage: { fontSize: 12, color: Palette.textMuted, marginTop: 10, textAlign: 'center' },
  section: { fontSize: 13, fontWeight: '700', color: Palette.textMuted, textTransform: 'uppercase', marginTop: 20, marginLeft: 4 },
  card: { backgroundColor: Palette.white, borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: Palette.border, gap: 4 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  file: { fontSize: 15, fontWeight: '700', color: Palette.text, flex: 1 },
  meta: { fontSize: 13, color: Palette.textMuted },
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  badgeText: { fontSize: 12, fontWeight: '700' },
  link: { color: Palette.primary, fontWeight: '700', fontSize: 14, marginTop: 4 },
});
