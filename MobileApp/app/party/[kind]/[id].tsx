import React, { useEffect, useState } from 'react';
import { Alert, KeyboardAvoidingView, Linking, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Centered } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { deleteParty, getParty, LABEL, Party, PartyInput, PartyKind, PERMISSION, saveParty } from '@/services/parties';

const EMPTY: PartyInput = { name: '', address: '', gst_number: '', state: '', state_code: '', phone_number: '' };

const toForm = (p: Party): PartyInput => ({
  name: p.name, address: p.address ?? '', gst_number: p.gst_number ?? '', state: p.state ?? '',
  state_code: p.state_code != null ? String(p.state_code) : '', phone_number: p.phone_number ?? '',
});

const open = (url: string) => Linking.openURL(url).catch(() => Alert.alert('Could not open', 'No app is available to handle this.'));
// wa.me needs digits only, with the country code and no leading zeros. Indian numbers are usually stored as
// 10 digits, often with a trunk-prefix 0 (098765…) or 00/+91 — strip all that, then add 91 if it's a bare 10-digit number.
const waNumber = (phone: string) => {
  const d = phone.replace(/\D/g, '').replace(/^0+/, '');
  return d.length === 10 ? `91${d}` : d;
};
const shortDate = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
};

function Action({ icon, label, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.action} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={22} color={Palette.primary} />
      <Text style={styles.actionLabel}>{label}</Text>
    </TouchableOpacity>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue} selectable>{value}</Text>
    </View>
  );
}

export default function PartyScreen() {
  const { kind: rawKind, id: rawId } = useLocalSearchParams<{ kind: string; id: string }>();
  const kind = (rawKind === 'vendor' ? 'vendor' : 'customer') as PartyKind;
  const isNew = rawId === 'new';
  const id = isNew ? undefined : Number(rawId);
  const canManage = useCan(PERMISSION[kind]);
  const hasReports = useFeature('advanced_reports');
  const canReport = useCan('report.view');
  const qc = useQueryClient();

  const [form, setForm] = useState<PartyInput>(EMPTY);
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const set = (k: keyof PartyInput) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const q = useQuery({ queryKey: ['party', kind, id], queryFn: () => getParty(kind, id!), enabled: !isNew });
  useEffect(() => {
    const p = q.data;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync local form state from fetched server data / a prop change
    if (p) setForm(toForm(p));
  }, [q.data]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['parties', kind] });
    qc.invalidateQueries({ queryKey: ['party-picker', kind] });
    qc.invalidateQueries({ queryKey: ['party', kind, id] });
  };

  const save = async () => {
    if (!form.name.trim()) return Alert.alert('Name required', `Enter the ${kind}'s name.`);
    if (form.gst_number.trim() && form.gst_number.trim().length !== 15) return Alert.alert('Invalid GSTIN', 'A GSTIN has 15 characters.');
    setSaving(true);
    try {
      await saveParty(kind, form, id);
      refresh();
      if (isNew) router.back();
      else setEditMode(false);
    } catch (e) {
      Alert.alert('Could not save', errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = () => Alert.alert(`Delete ${kind}`, 'This cannot be undone.', [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Delete', style: 'destructive', onPress: async () => {
      try { await deleteParty(kind, id!); refresh(); router.back(); }
      catch (e) { Alert.alert('Could not delete', errorMessage(e)); }
    } },
  ]);

  const p = q.data;
  const editing = isNew || editMode;
  const dirty = !!p && JSON.stringify(form) !== JSON.stringify(toForm(p));

  const cancelEdit = () => {
    const discard = () => { if (p) setForm(toForm(p)); setEditMode(false); };
    if (!dirty) return discard();
    Alert.alert('Discard changes?', 'Your edits will be lost.', [
      { text: 'Keep editing', style: 'cancel' },
      { text: 'Discard', style: 'destructive', onPress: discard },
    ]);
  };

  if (!isNew && q.isLoading) return <Centered />;
  if (!isNew && !p) return <Centered><Text style={styles.detailValue}>{errorMessage(q.error)}</Text></Centered>;

  const headerRight = () => {
    if (editing) {
      return (
        <TouchableOpacity onPress={save} disabled={saving} hitSlop={8} accessibilityRole="button" accessibilityLabel="Save">
          <Text style={[styles.headerBtn, saving && { opacity: 0.5 }]}>Save</Text>
        </TouchableOpacity>
      );
    }
    if (!canManage) return null;
    return (
      <TouchableOpacity onPress={() => setEditMode(true)} hitSlop={8} accessibilityRole="button" accessibilityLabel="Edit">
        <Text style={styles.headerBtn}>Edit</Text>
      </TouchableOpacity>
    );
  };
  const headerLeft = !isNew && editing
    ? () => (
      <TouchableOpacity onPress={cancelEdit} hitSlop={8} accessibilityRole="button" accessibilityLabel="Cancel">
        <Text style={[styles.headerBtn, { color: Palette.textMuted }]}>Cancel</Text>
      </TouchableOpacity>
    )
    : undefined;

  return (
    <>
      <Stack.Screen options={{ title: isNew ? `New ${kind}` : LABEL[kind], headerRight, ...(headerLeft ? { headerLeft } : {}), gestureEnabled: !editing || isNew }} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, backgroundColor: Palette.white }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          {editing ? (
            <>
              <Field label="Name" value={form.name} onChangeText={set('name')} />
              <Field label="Phone" value={form.phone_number} onChangeText={set('phone_number')} keyboardType="phone-pad" maxLength={15} />
              <Field label="GST number" value={form.gst_number} onChangeText={set('gst_number')} autoCapitalize="characters" maxLength={15} />
              <Field label="Address" value={form.address} onChangeText={set('address')} multiline />
              <View style={styles.row}>
                <View style={{ flex: 2 }}><Field label="State" value={form.state} onChangeText={set('state')} /></View>
                <View style={{ flex: 1 }}><Field label="Code" value={form.state_code} onChangeText={set('state_code')} keyboardType="number-pad" maxLength={2} /></View>
              </View>
              {!isNew && <Button title={`Delete ${kind}`} variant="danger" onPress={remove} style={{ marginTop: 12 }} />}
            </>
          ) : p && (
            <>
              <View style={styles.card}>
                <Text style={styles.name}>{p.name}</Text>
                {!!p.gst_number && <Text style={styles.gstin} selectable>GSTIN {p.gst_number}</Text>}
                {p.invoice_count != null && (
                  <View style={styles.stats}>
                    <View style={styles.stat}><Text style={styles.statValue}>{p.invoice_count}</Text><Text style={styles.statLabel}>Invoices</Text></View>
                    <View style={styles.stat}><Text style={styles.statValue}>{money(p.total_billed ?? 0)}</Text><Text style={styles.statLabel}>Total billed</Text></View>
                    <View style={styles.stat}><Text style={styles.statValue}>{p.last_invoice_date ? shortDate(p.last_invoice_date) : '—'}</Text><Text style={styles.statLabel}>Last invoice</Text></View>
                  </View>
                )}
                {(!!p.phone_number || !!p.address) && (
                  <View style={styles.actions}>
                    {!!p.phone_number && <Action icon="call-outline" label="Call" onPress={() => open(`tel:${p.phone_number}`)} />}
                    {!!p.phone_number && <Action icon="logo-whatsapp" label="WhatsApp" onPress={() => open(`https://wa.me/${waNumber(p.phone_number!)}`)} />}
                    {!!p.address && <Action icon="location-outline" label="Map" onPress={() => open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([p.address, p.state].filter(Boolean).join(', '))}`)} />}
                  </View>
                )}
              </View>
              <View style={styles.card}>
                <Row label="Phone" value={p.phone_number || '—'} />
                <Row label="Address" value={p.address || '—'} />
                <Row label="State" value={p.state ? `${p.state}${p.state_code != null ? ` (${p.state_code})` : ''}` : '—'} />
              </View>
              {hasReports && canReport && (
                <Button title="View ledger" variant="outline" onPress={() => router.push(`/reports/ledger/${kind}/${id}`)} />
              )}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 24 },
  row: { flexDirection: 'row', gap: 12 },
  headerBtn: { fontSize: 16, fontWeight: '700', color: Palette.primary },
  card: { backgroundColor: Palette.surface, borderWidth: 1, borderColor: Palette.border, borderRadius: 16, padding: 16, marginBottom: 16 },
  name: { fontSize: 22, fontWeight: '800', color: Palette.text },
  gstin: { fontSize: 13, color: Palette.textMuted, marginTop: 4, fontWeight: '600' },
  stats: { flexDirection: 'row', marginTop: 16, gap: 8 },
  stat: { flex: 1 },
  statValue: { fontSize: 15, fontWeight: '800', color: Palette.text },
  statLabel: { fontSize: 12, color: Palette.textMuted, marginTop: 2 },
  actions: { flexDirection: 'row', gap: 10, marginTop: 16 },
  action: { flex: 1, alignItems: 'center', gap: 4, paddingVertical: 10, borderRadius: 12, backgroundColor: Palette.white, borderWidth: 1, borderColor: Palette.border },
  actionLabel: { fontSize: 12, fontWeight: '700', color: Palette.label },
  detailRow: { paddingVertical: 8 },
  detailLabel: { fontSize: 12, fontWeight: '700', color: Palette.textMuted, marginBottom: 2 },
  detailValue: { fontSize: 16, color: Palette.text, fontWeight: '500' },
});
