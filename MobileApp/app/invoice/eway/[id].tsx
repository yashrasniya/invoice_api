import React, { useEffect, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Stack, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker from '@react-native-community/datetimepicker';
import * as Sharing from 'expo-sharing';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Section } from '@/components/report-ui';
import { StatePicker } from '@/components/state-picker';
import { Button } from '@/components/ui/button';
import { Centered, Chip, EmptyState } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { useCan, useFeature } from '@/hooks/use-access';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { parseYmd, ymd } from '@/lib/invoice-dates';
import { errorMessage } from '@/services/api';
import {
  downloadEwayJson, EwayBill, EwayBillInput, EwayIssue, fetchEway, formatEwayTime, MODE_LABEL, saveEway,
  SUB_SUPPLY_LABEL, TransportMode,
} from '@/services/eway';

type Form = Omit<EwayBill, 'source' | 'updated_at' | 'ewb_date' | 'valid_until' | 'status' | 'distance_km'> & { distance_km: string };

const toForm = (e: EwayBill): Form => ({
  sub_supply_type: e.sub_supply_type, doc_type: e.doc_type,
  ship_to_name: e.ship_to_name, ship_to_address: e.ship_to_address, ship_to_place: e.ship_to_place,
  ship_to_state_code: e.ship_to_state_code, ship_to_pincode: e.ship_to_pincode,
  distance_km: e.distance_km ? String(e.distance_km) : '',
  transport_mode: e.transport_mode, vehicle_number: e.vehicle_number, vehicle_type: e.vehicle_type,
  transporter_id: e.transporter_id, transporter_name: e.transporter_name,
  transport_doc_number: e.transport_doc_number, transport_doc_date: e.transport_doc_date,
  ewb_number: e.ewb_number,
});

function IssueRow({ issue }: { issue: EwayIssue }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.issue}>
      <Ionicons name={issue.level === 'error' ? 'close-circle' : 'alert-circle'} size={18}
        color={issue.level === 'error' ? theme.danger : theme.warning} />
      <Text style={styles.issueText}>{issue.message}</Text>
    </View>
  );
}

/** Transport details for one sales invoice, the portal JSON, and the EWB number typed back in. */
export default function EwayBillScreen() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const { id: raw } = useLocalSearchParams<{ id: string }>();
  const id = Number(raw);
  const qc = useQueryClient();
  const hasFeature = useFeature('eway_bill');
  const canEdit = useCan('invoice.update');
  const q = useQuery({ queryKey: ['eway', id], queryFn: () => fetchEway(id), enabled: hasFeature });
  const d = q.data;
  const [form, setForm] = useState<Form | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync local form state from fetched server data
    if (d) setForm(toForm(d.eway_bill));
  }, [d]);

  if (!hasFeature) {
    return (
      <>
        <Stack.Screen options={{ title: 'E-way bill' }} />
        <EmptyState icon="lock-closed-outline" title="E-way bills are not in your plan"
          hint="Upgrade your plan on the web to prepare e-way bills for your invoices." />
      </>
    );
  }
  if (q.isLoading || (d && !form)) return <Centered />;
  if (q.error || !d || !form) {
    return <EmptyState icon="alert-circle-outline" title="Couldn't load the e-way bill" hint={errorMessage(q.error)} />;
  }

  const ewb = d.eway_bill;
  const generated = ewb.status === 'generated';
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => (f ? { ...f, [key]: value } : f));
  const road = form.transport_mode === 1;

  const payload = (): EwayBillInput => {
    const { distance_km, ewb_number: _n, ...rest } = form;
    return { ...rest, distance_km: Number(distance_km.replace(/[^0-9]/g, '')) || 0 };
  };

  const persist = async (key: string, input: EwayBillInput) => {
    setBusy(key);
    try {
      const saved = await saveEway(id, input);
      qc.setQueryData(['eway', id], saved);
      void qc.invalidateQueries({ queryKey: ['eway-pending'] });
      return saved;
    } catch (e) {
      Alert.alert('Could not save', errorMessage(e));
      return null;
    } finally {
      setBusy(null);
    }
  };

  const share = async () => {
    // save first so the file matches what's on screen
    const saved = await persist('json', payload());
    if (!saved) return;
    if (!saved.ready) { Alert.alert('Not ready yet', 'Fix the items marked in red first.'); return; }
    setBusy('json');
    try {
      const uri = await downloadEwayJson([id], d.invoice.invoice_number || String(id));
      if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing is not available on this device.');
      await Sharing.shareAsync(uri, { mimeType: 'application/json', dialogTitle: 'E-way bill file', UTI: 'public.json' });
    } catch (e) {
      Alert.alert('Could not prepare the file', errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const saveNumber = () => {
    const n = form.ewb_number.replace(/\s+/g, '');
    if (!/^\d{12}$/.test(n)) { Alert.alert('Check the number', 'An e-way bill number is 12 digits.'); return; }
    void persist('number', { ...payload(), ewb_number: n });
  };

  const cancel = () => Alert.alert('Cancelled on the portal?',
    'Only mark it cancelled after cancelling it on the e-way bill portal (allowed within 24 hours).', [
      { text: 'Back', style: 'cancel' },
      { text: 'Mark cancelled', style: 'destructive', onPress: () => { void persist('cancel', { status: 'cancelled' }); } },
    ]);

  const errors = d.issues.filter((i) => i.level === 'error');
  const warnings = d.issues.filter((i) => i.level === 'warning');
  const v = d.verdict;

  return (
    <>
      <Stack.Screen options={{ title: d.invoice.invoice_number ? `E-way bill · #${d.invoice.invoice_number}` : 'E-way bill' }} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.screen}>
        <ScrollView contentContainerStyle={{ padding: 16, gap: 4, paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
          <View style={[styles.status, { borderColor: generated ? theme.success : v.needed ? theme.warning : theme.border }]}>
            <Ionicons name={generated ? 'checkmark-circle' : v.needed ? 'alert-circle' : 'information-circle'} size={22}
              color={generated ? theme.success : v.needed ? theme.warning : theme.textMuted} />
            <View style={{ flex: 1 }}>
              <Text style={styles.statusText}>
                {generated ? `E-way bill ${ewb.ewb_number}` : ewb.status === 'cancelled' ? `E-way bill ${ewb.ewb_number} cancelled`
                  : v.needed ? 'This invoice needs an e-way bill' : 'E-way bill optional'}
              </Text>
              <Text style={styles.sub}>
                {generated && ewb.valid_until ? `Valid until ${formatEwayTime(ewb.valid_until)}` : v.reason}
              </Text>
            </View>
          </View>
          {!canEdit && <Text style={styles.banner}>You can view these details; editing needs permission to update invoices.</Text>}

          {!generated && errors.length > 0 && (
            <Section title={`Fix before the file (${errors.length})`}>
              {errors.map((i, n) => <IssueRow key={`e${n}`} issue={i} />)}
            </Section>
          )}
          {!generated && warnings.length > 0 && (
            <Section title="Worth a look">
              {warnings.map((i, n) => <IssueRow key={`w${n}`} issue={i} />)}
            </Section>
          )}

          <Section title="Transport (Part B)">
            <Text style={styles.label}>Mode</Text>
            <View style={styles.chips}>
              {([1, 2, 3, 4] as TransportMode[]).map((m) => (
                <Chip key={m} label={MODE_LABEL[m]} active={form.transport_mode === m}
                  onPress={() => canEdit && set('transport_mode', m)} />
              ))}
            </View>
            {road && (
              <>
                <Field label="Vehicle number" value={form.vehicle_number} editable={canEdit} autoCapitalize="characters"
                  autoCorrect={false} maxLength={15} placeholder="KA01AB1234"
                  hint="Leave blank if the transporter will add it on the portal."
                  onChangeText={(t) => set('vehicle_number', t.toUpperCase())} />
                <View style={styles.chips}>
                  <Chip label="Regular vehicle" active={form.vehicle_type === 'R'} onPress={() => canEdit && set('vehicle_type', 'R')} />
                  <Chip label="Over-dimensional cargo" active={form.vehicle_type === 'O'} onPress={() => canEdit && set('vehicle_type', 'O')} />
                </View>
              </>
            )}
            <Field label="Transporter ID (GSTIN / TRANSIN)" value={form.transporter_id} editable={canEdit}
              autoCapitalize="characters" autoCorrect={false} maxLength={15}
              onChangeText={(t) => set('transporter_id', t.toUpperCase())} />
            <Field label="Transporter name" value={form.transporter_name} editable={canEdit} maxLength={100}
              onChangeText={(t) => set('transporter_name', t)} />
            <Field label={road ? 'LR / transport doc no. (optional)' : 'RR / airway bill / B/L no.'} value={form.transport_doc_number}
              editable={canEdit} autoCapitalize="characters" maxLength={15} onChangeText={(t) => set('transport_doc_number', t)} />
            <Text style={styles.label}>Transport document date</Text>
            <TouchableOpacity style={styles.select} disabled={!canEdit} onPress={() => setPicking(true)}
              accessibilityRole="button" accessibilityLabel="Transport document date">
              <Text style={[styles.selectText, !form.transport_doc_date && { color: theme.textFaint }]}>
                {form.transport_doc_date ?? 'Not set'}
              </Text>
              <Ionicons name="calendar-outline" size={18} color={theme.textMuted} />
            </TouchableOpacity>
            {picking && (
              <DateTimePicker value={parseYmd(form.transport_doc_date ?? ymd(new Date()))} mode="date" themeVariant={theme.scheme}
                display={Platform.OS === 'ios' ? 'inline' : 'default'}
                onChange={(_, dt) => { if (Platform.OS !== 'ios') setPicking(false); if (dt) set('transport_doc_date', ymd(dt)); }} />
            )}
            {picking && Platform.OS === 'ios' && (
              <Button title="Done" variant="outline" onPress={() => setPicking(false)} style={{ height: 44, marginTop: 8 }} />
            )}
            <Field label="Distance (km)" value={form.distance_km} editable={canEdit} keyboardType="number-pad" maxLength={4}
              hint={d.validity_if_generated_now
                ? `Generated now, it would be valid until ${formatEwayTime(d.validity_if_generated_now)}.`
                : 'Leave blank to let the portal work out the PIN-to-PIN distance.'}
              onChangeText={(t) => set('distance_km', t.replace(/[^0-9]/g, ''))} />
          </Section>

          <Section title="Ship to (optional)">
            <Text style={[styles.hint, { marginTop: 0, marginBottom: 10 }]}>
              Only if the goods go somewhere other than the customer&apos;s address. For an export, the port or airport.
            </Text>
            <Field label="Address" value={form.ship_to_address} editable={canEdit} maxLength={240}
              onChangeText={(t) => set('ship_to_address', t)} />
            <Field label="City / place" value={form.ship_to_place} editable={canEdit} maxLength={50}
              onChangeText={(t) => set('ship_to_place', t)} />
            <View style={styles.row}>
              <View style={{ flex: 1 }}>
                <Field label="PIN code" value={form.ship_to_pincode} editable={canEdit} keyboardType="number-pad" maxLength={6}
                  onChangeText={(t) => set('ship_to_pincode', t.replace(/[^0-9]/g, ''))} />
              </View>
            </View>
            <StatePicker label="State" value={form.ship_to_state_code} locked={!canEdit}
              onChange={(code) => set('ship_to_state_code', code)} />
          </Section>

          <Section title="Document">
            <View style={styles.chips}>
              {([1, 3, 9] as const).map((s) => (
                <Chip key={s} label={SUB_SUPPLY_LABEL[s]} active={form.sub_supply_type === s}
                  onPress={() => canEdit && set('sub_supply_type', s)} />
              ))}
            </View>
            <View style={[styles.chips, { marginTop: 8 }]}>
              <Chip label="Tax invoice" active={form.doc_type === 'INV'} onPress={() => canEdit && set('doc_type', 'INV')} />
              <Chip label="Bill of supply" active={form.doc_type === 'BIL'} onPress={() => canEdit && set('doc_type', 'BIL')} />
            </View>
          </Section>

          {canEdit && !generated && (
            <>
              <Button title="Save details" variant="outline" onPress={() => { void persist('save', payload()); }} loading={busy === 'save'} />
              <Button title="Share e-way bill JSON" onPress={share} loading={busy === 'json'} style={{ marginTop: 10 }} />
              <Text style={styles.note}>
                Upload the file on ewaybillgst.gov.in (e-Waybill → Generate Bulk), then type the e-way bill number below.
              </Text>
            </>
          )}

          <Section title="E-way bill number">
            <Field label="12-digit number from the portal" value={form.ewb_number} editable={canEdit && !generated}
              keyboardType="number-pad" maxLength={14} placeholder="3310 0123 4567"
              onChangeText={(t) => set('ewb_number', t.replace(/[^0-9 ]/g, ''))} />
            {canEdit && !generated && (
              <Button title="Save number" onPress={saveNumber} loading={busy === 'number'} style={{ marginTop: 10 }} />
            )}
            {canEdit && generated && (
              <Button title="Mark cancelled" variant="danger" onPress={cancel} loading={busy === 'cancel'} style={{ marginTop: 10 }} />
            )}
            {generated && <Text style={styles.hint}>It prints on the invoice PDF where the template has an e-way bill field.</Text>}
          </Section>
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.background },
  status: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1.5, borderRadius: 14, padding: 12, marginBottom: 12, backgroundColor: t.surface },
  statusText: { fontSize: 15, fontWeight: '700', color: t.text },
  sub: { fontSize: 12, color: t.textMuted, marginTop: 2 },
  banner: { fontSize: 13, color: t.text, backgroundColor: t.primarySoft, borderRadius: 12, padding: 12, marginBottom: 12, lineHeight: 18 },
  issue: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border },
  issueText: { fontSize: 13, color: t.text, lineHeight: 18, flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 },
  row: { flexDirection: 'row', gap: 12 },
  label: { fontSize: 14, fontWeight: '700', color: t.label, marginBottom: 6 },
  select: { height: 50, borderRadius: 12, backgroundColor: t.isDark ? t.surfaceRaised : t.background, borderWidth: 1.5,
    borderColor: t.border, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },
  selectText: { fontSize: 16, color: t.text },
  hint: { fontSize: 12, color: t.textMuted, marginTop: 8, lineHeight: 17 },
  note: { fontSize: 12, color: t.textMuted, textAlign: 'center', marginTop: 10, marginBottom: 12, lineHeight: 17 },
});
