import React, { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { StatePicker } from '@/components/state-picker';
import { GST_STATES, gstinError, isValidGstin, normalizeGstin, stateFromGstin } from '@/constants/gst';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import api, { errorMessage } from '@/services/api';
import { fetchProfile } from '@/services/auth';
import { useSession } from '@/store/session';

type Form = { company_name: string; company_address: string; company_gst_number: string; company_email_id: string; company_phone: string };

export default function CompanySetupScreen() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const [form, setForm] = useState<Form>({
    company_name: '', company_address: '', company_gst_number: '', company_email_id: '', company_phone: '',
  });
  const [hasGst, setHasGst] = useState(true);
  const [stateCode, setStateCode] = useState<number | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const set = (k: keyof Form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const gstState = hasGst ? stateFromGstin(form.company_gst_number) : null;

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.company_name.trim()) e.company_name = 'Required';
    if (!form.company_address.trim()) e.company_address = 'Required';
    if (!form.company_email_id.trim()) e.company_email_id = 'Required';
    if (hasGst) {
      { const bad = gstinError(form.company_gst_number) ?? (isValidGstin(form.company_gst_number) ? null : 'Enter a valid 15-character GST number'); if (bad) e.company_gst_number = bad; }
    } else if (stateCode === null) {
      e.state = 'Select your state';
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = async () => {
    if (!validate()) return;
    setLoading(true);
    try {
      const state = hasGst ? gstState! : GST_STATES.find((s) => s.code === stateCode)!;
      await api.post('user-companies/', {
        company_name: form.company_name.trim(),
        company_address: form.company_address.trim(),
        company_email_id: form.company_email_id.trim(),
        company_phone: form.company_phone.trim(),
        company_gst_number: hasGst ? normalizeGstin(form.company_gst_number) : '',
        state: state.name,
        state_code: state.code,
      });
      // flips is_company_varified, which the root layout watches to reveal the tabs
      useSession.getState().setUser(await fetchProfile());
      await useSession.getState().refreshAccess();
    } catch (e) {
      Alert.alert('Could not save company', errorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Set up your company</Text>
        <Text style={styles.subtitle}>These details appear on your invoices. You can add bank and UPI details later.</Text>

        <Field label="Company name" value={form.company_name} onChangeText={set('company_name')} maxLength={100} error={errors.company_name} />
        <Field label="Address" value={form.company_address} onChangeText={set('company_address')} maxLength={255}
          error={errors.company_address} />

        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>I don&apos;t have a GST number</Text>
          <Switch value={!hasGst} onValueChange={(v) => { setHasGst(!v); setErrors({}); }} trackColor={{ true: theme.primary }} />
        </View>

        {hasGst ? (
          <>
            <Field label="GST number" placeholder="29ABCDE1234F1ZW" value={form.company_gst_number}
              onChangeText={set('company_gst_number')} autoCapitalize="characters" autoCorrect={false} maxLength={15}
              error={errors.company_gst_number} />
            {!!gstState && (
              <Text style={styles.derived}>State: {gstState.name} ({String(gstState.code).padStart(2, '0')}), from your GST number</Text>
            )}
          </>
        ) : (
          <StatePicker label="State" value={stateCode} onChange={setStateCode} error={errors.state} />
        )}

        <Field label="Company email" value={form.company_email_id} onChangeText={set('company_email_id')} autoCapitalize="none"
          keyboardType="email-address" maxLength={254} error={errors.company_email_id} />
        <Field label="Phone (optional)" value={form.company_phone} onChangeText={set('company_phone')} keyboardType="phone-pad" maxLength={20} />

        <Button title="Save and continue" onPress={submit} loading={loading} style={{ marginTop: 8 }} />
        <Button title="Sign out" variant="outline" onPress={() => useSession.getState().signOut()} style={{ marginTop: 12 }} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  container: { flex: 1, backgroundColor: t.surface },
  scroll: { paddingHorizontal: 24, paddingVertical: 64 },
  title: { fontSize: 26, fontWeight: '800', color: t.text, marginBottom: 8 },
  subtitle: { fontSize: 15, color: t.textMuted, marginBottom: 24, lineHeight: 21 },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, marginLeft: 4 },
  switchLabel: { fontSize: 15, fontWeight: '600', color: t.label },
  derived: { marginTop: -8, marginBottom: 18, marginLeft: 4, fontSize: 13, color: t.success, fontWeight: '600' },
});
