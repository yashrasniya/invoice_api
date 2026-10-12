import React, { useEffect, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Centered } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';
import { errorMessage } from '@/services/api';
import { deleteParty, getParty, LABEL, PartyInput, PartyKind, PERMISSION, saveParty } from '@/services/parties';

const EMPTY: PartyInput = { name: '', address: '', gst_number: '', state: '', state_code: '', phone_number: '' };

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
  const [saving, setSaving] = useState(false);
  const set = (k: keyof PartyInput) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const q = useQuery({ queryKey: ['party', kind, id], queryFn: () => getParty(kind, id!), enabled: !isNew });
  useEffect(() => {
    const p = q.data;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync local form state from fetched server data / a prop change
    if (p) setForm({
      name: p.name, address: p.address ?? '', gst_number: p.gst_number ?? '', state: p.state ?? '',
      state_code: p.state_code != null ? String(p.state_code) : '', phone_number: p.phone_number ?? '',
    });
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
      router.back();
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

  if (!isNew && q.isLoading) return <Centered />;
  const editable = canManage;

  return (
    <>
      <Stack.Screen options={{ title: isNew ? `New ${kind}` : LABEL[kind] }} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, backgroundColor: Palette.white }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Field label="Name" value={form.name} onChangeText={set('name')} editable={editable} />
          <Field label="Phone" value={form.phone_number} onChangeText={set('phone_number')} keyboardType="phone-pad" editable={editable} maxLength={15} />
          <Field label="GST number" value={form.gst_number} onChangeText={set('gst_number')} autoCapitalize="characters" editable={editable} maxLength={15} />
          <Field label="Address" value={form.address} onChangeText={set('address')} editable={editable} multiline />
          <View style={styles.row}>
            <View style={{ flex: 2 }}><Field label="State" value={form.state} onChangeText={set('state')} editable={editable} /></View>
            <View style={{ flex: 1 }}><Field label="Code" value={form.state_code} onChangeText={set('state_code')} keyboardType="number-pad" editable={editable} maxLength={2} /></View>
          </View>
          {!isNew && hasReports && canReport && (
            <Button title="View ledger" variant="outline" onPress={() => router.push(`/reports/ledger/${kind}/${id}`)} style={{ marginBottom: 12 }} />
          )}
          {editable && <Button title="Save" onPress={save} loading={saving} />}
          {editable && !isNew && <Button title={`Delete ${kind}`} variant="danger" onPress={remove} style={{ marginTop: 12 }} />}
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 24 },
  row: { flexDirection: 'row', gap: 12 },
});
