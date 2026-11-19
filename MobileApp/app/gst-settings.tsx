import React, { useEffect, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Switch, Text, TouchableOpacity, View } from 'react-native';
import { Stack, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker from '@react-native-community/datetimepicker';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Section } from '@/components/report-ui';
import { Button } from '@/components/ui/button';
import { Centered, Chip, EmptyState } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { parseYmd, ymd } from '@/lib/invoice-dates';
import { useFeature } from '@/hooks/use-access';
import { errorMessage } from '@/services/api';
import { useSession } from '@/store/session';
import { fetchGstSettings, GstSettingsInput, saveGstSettings } from '@/services/company';

type DateKey = 'lut_valid_from' | 'lut_valid_to';

/** First and last day of the financial year containing today: an LUT is filed per FY. */
function currentFy() {
  const now = new Date();
  const y = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return { from: `${y}-04-01`, to: `${y + 1}-03-31` };
}

/** GST filing frequency and Letter of Undertaking (LUT), for company admins. */
export default function GstSettingsScreen() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['gst-settings'], queryFn: fetchGstSettings });
  const [form, setForm] = useState<GstSettingsInput>({
    gst_filing_frequency: 'monthly', lut_number: '', lut_valid_from: null, lut_valid_to: null, city: '', pincode: '', enable_eway_bill: true,
  });
  const planHasEway = useFeature('eway_bill');
  const [picking, setPicking] = useState<DateKey | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = q.data;
    if (!d) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync local form state from fetched server data / a prop change
    setForm({ gst_filing_frequency: d.gst_filing_frequency, lut_number: d.lut_number ?? '',
      lut_valid_from: d.lut_valid_from, lut_valid_to: d.lut_valid_to, city: d.city ?? '', pincode: d.pincode ?? '',
      enable_eway_bill: d.enable_eway_bill !== false });
  }, [q.data]);

  const canEdit = !!q.data?.can_edit;
  const hasLut = !!(form.lut_number.trim() || form.lut_valid_from || form.lut_valid_to);

  const save = async () => {
    setError(null);
    if (hasLut && !(form.lut_number.trim() && form.lut_valid_from && form.lut_valid_to)) {
      setError('Enter the LUT number and both dates it is valid for, or clear all three.');
      return;
    }
    if (form.pincode.trim() && !/^[1-9]\d{5}$/.test(form.pincode.trim())) {
      setError('A PIN code is 6 digits.');
      return;
    }
    if (form.lut_valid_from && form.lut_valid_to && form.lut_valid_to < form.lut_valid_from) {
      setError("The end date can't be before the start date.");
      return;
    }
    setSaving(true);
    try {
      const saved = await saveGstSettings(form);
      qc.setQueryData(['gst-settings'], saved);
      // the returns read the filing frequency and LUT
      void qc.invalidateQueries({ queryKey: ['report-gstr1'] });
      void qc.invalidateQueries({ queryKey: ['report-gstr3b'] });
      void qc.invalidateQueries({ queryKey: ['eway'] });
      // the invoice screen reads the e-way bill switch from access
      void useSession.getState().refreshAccess().catch(() => {});
      router.back();
    } catch (e) {
      Alert.alert('Could not save', errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const dateRow = (key: DateKey, label: string) => (
    <View style={{ flex: 1 }}>
      <Text style={styles.label}>{label}</Text>
      <TouchableOpacity style={styles.select} disabled={!canEdit} onPress={() => setPicking(key)}
        accessibilityRole="button" accessibilityLabel={label}>
        <Text style={[styles.selectText, !form[key] && { color: theme.textFaint }]}>{form[key] ?? 'Not set'}</Text>
        <Ionicons name="calendar-outline" size={18} color={theme.textMuted} />
      </TouchableOpacity>
    </View>
  );

  return (
    <>
      <Stack.Screen options={{ title: 'GST settings' }} />
      {q.isLoading ? <Centered /> : q.error || !q.data ? (
        <EmptyState icon="alert-circle-outline" title="Couldn't load GST settings" hint={errorMessage(q.error)} />
      ) : (
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.screen}>
          <ScrollView contentContainerStyle={{ padding: 16, gap: 4 }} keyboardShouldPersistTaps="handled">
            <Text style={styles.meta}>
              GSTIN {q.data.company_gst_number || '—'}{q.data.state ? ` · ${q.data.state}` : ''}
            </Text>
            {!canEdit && (
              <Text style={styles.banner}>Only a company admin can change these settings.</Text>
            )}

            <Section title="Return filing">
              <View style={styles.chips}>
                <Chip label="Monthly" active={form.gst_filing_frequency === 'monthly'}
                  onPress={() => canEdit && setForm((f) => ({ ...f, gst_filing_frequency: 'monthly' }))} />
                <Chip label="Quarterly (QRMP)" active={form.gst_filing_frequency === 'quarterly'}
                  onPress={() => canEdit && setForm((f) => ({ ...f, gst_filing_frequency: 'quarterly' }))} />
              </View>
              <Text style={styles.hint}>
                {form.gst_filing_frequency === 'quarterly'
                  ? 'GSTR-1 for the first two months of a quarter becomes the IFF (B2B invoices only); the full return is filed per quarter.'
                  : 'GSTR-1 and GSTR-3B are filed every month.'}
              </Text>
            </Section>

            <Section title="Export / SEZ under LUT">
              <Text style={[styles.hint, { marginBottom: 10 }]}>
                Needed only if you export or supply to an SEZ without charging IGST. Filed once per financial year
                on the GST portal.
              </Text>
              <Field label="LUT number (ARN)" value={form.lut_number} editable={canEdit} autoCapitalize="characters"
                autoCorrect={false} maxLength={30} placeholder="AD290326000001X"
                onChangeText={(v) => setForm((f) => ({ ...f, lut_number: v }))} />
              <View style={styles.row}>
                {dateRow('lut_valid_from', 'Valid from')}
                {dateRow('lut_valid_to', 'Valid to')}
              </View>
              {canEdit && (
                <View style={[styles.chips, { marginTop: 12 }]}>
                  <Chip label="This financial year" active={false}
                    onPress={() => { const fy = currentFy(); setForm((f) => ({ ...f, lut_valid_from: fy.from, lut_valid_to: fy.to })); }} />
                  {hasLut && (
                    <Chip label="Clear LUT" active={false}
                      onPress={() => setForm((f) => ({ ...f, lut_number: '', lut_valid_from: null, lut_valid_to: null }))} />
                  )}
                </View>
              )}
            </Section>

            {planHasEway && (
              <Section title="E-way bills">
                <View style={styles.switchRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.label}>Use e-way bills</Text>
                    <Text style={[styles.hint, { marginTop: 0 }]}>
                      Turn off to hide e-way bills from invoices. Saved e-way bills are kept.
                    </Text>
                  </View>
                  <Switch value={form.enable_eway_bill} disabled={!canEdit} trackColor={{ true: theme.primary }}
                    accessibilityLabel="Use e-way bills"
                    onValueChange={(v) => setForm((f) => ({ ...f, enable_eway_bill: v }))} />
                </View>
              </Section>
            )}

            {(!planHasEway || form.enable_eway_bill) && (
              <Section title="E-way bills: dispatch from">
                <Text style={[styles.hint, { marginTop: 0, marginBottom: 10 }]}>
                  The place goods leave from. E-way bills need the PIN code.
                </Text>
                <Field label="City / place" value={form.city} editable={canEdit} maxLength={50}
                  onChangeText={(v) => setForm((f) => ({ ...f, city: v }))} />
                <Field label="PIN code" value={form.pincode} editable={canEdit} keyboardType="number-pad" maxLength={6}
                  onChangeText={(v) => setForm((f) => ({ ...f, pincode: v.replace(/[^0-9]/g, '') }))} />
              </Section>
            )}

            {picking && (
              <DateTimePicker
                value={parseYmd(form[picking] ?? ymd(new Date()))} mode="date" themeVariant={theme.scheme}
                display={Platform.OS === 'ios' ? 'inline' : 'default'}
                onChange={(_, d) => {
                  const key = picking;
                  if (Platform.OS !== 'ios') setPicking(null);
                  if (d) setForm((f) => ({ ...f, [key]: ymd(d) }));
                }}
              />
            )}
            {picking && Platform.OS === 'ios' && (
              <Button title="Done" variant="outline" onPress={() => setPicking(null)} style={{ height: 44, marginBottom: 12 }} />
            )}

            {!!error && <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text>}
            {canEdit && <Button title="Save" onPress={save} loading={saving} style={{ marginTop: 8 }} />}
          </ScrollView>
        </KeyboardAvoidingView>
      )}
    </>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.background },
  meta: { fontSize: 12, color: t.textMuted, marginBottom: 10 },
  banner: { fontSize: 13, color: t.text, backgroundColor: t.primarySoft, borderRadius: 12, padding: 12, marginBottom: 12, lineHeight: 18 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  hint: { fontSize: 12, color: t.textMuted, marginTop: 8, lineHeight: 17 },
  row: { flexDirection: 'row', gap: 12 },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  label: { fontSize: 14, fontWeight: '700', color: t.label, marginBottom: 6 },
  select: { height: 50, borderRadius: 12, backgroundColor: t.isDark ? t.surfaceRaised : t.background, borderWidth: 1.5,
    borderColor: t.border, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  selectText: { fontSize: 16, color: t.text },
  error: { fontSize: 13, color: t.danger, marginTop: 8 },
});
