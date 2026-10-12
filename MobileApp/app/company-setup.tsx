import React, { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import api, { errorMessage } from '@/services/api';
import { fetchProfile } from '@/services/auth';
import { useSession } from '@/store/session';

type Form = {
  company_name: string; company_address: string; company_gst_number: string;
  state: string; state_code: string; company_email_id: string; company_phone: string;
};

export default function CompanySetupScreen() {
  const [form, setForm] = useState<Form>({
    company_name: '', company_address: '', company_gst_number: '',
    state: '', state_code: '', company_email_id: '', company_phone: '',
  });
  const [loading, setLoading] = useState(false);
  const set = (k: keyof Form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    const missing = (['company_name', 'company_address', 'company_gst_number', 'state', 'state_code', 'company_email_id'] as const)
      .filter((k) => !form[k].trim());
    if (missing.length) {
      Alert.alert('Missing details', 'Please fill in all fields except phone.');
      return;
    }
    setLoading(true);
    try {
      await api.post('user-companies/', {
        ...form,
        state_code: Number(form.state_code),
        company_gst_number: form.company_gst_number.trim().toUpperCase(),
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

        <Field label="Company name" value={form.company_name} onChangeText={set('company_name')} maxLength={30} />
        <Field label="Address" value={form.company_address} onChangeText={set('company_address')} maxLength={30} />
        <Field label="GST number" value={form.company_gst_number} onChangeText={set('company_gst_number')} autoCapitalize="characters" maxLength={30} />
        <View style={styles.row}>
          <View style={{ flex: 2 }}><Field label="State" value={form.state} onChangeText={set('state')} maxLength={30} /></View>
          <View style={{ flex: 1 }}><Field label="Code" value={form.state_code} onChangeText={set('state_code')} keyboardType="number-pad" maxLength={2} /></View>
        </View>
        <Field label="Company email" value={form.company_email_id} onChangeText={set('company_email_id')} autoCapitalize="none" keyboardType="email-address" maxLength={30} />
        <Field label="Phone (optional)" value={form.company_phone} onChangeText={set('company_phone')} keyboardType="phone-pad" maxLength={20} />

        <Button title="Save and continue" onPress={submit} loading={loading} style={{ marginTop: 8 }} />
        <Button title="Sign out" variant="outline" onPress={() => useSession.getState().signOut()} style={{ marginTop: 12 }} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Palette.white },
  scroll: { paddingHorizontal: 24, paddingVertical: 64 },
  title: { fontSize: 26, fontWeight: '800', color: Palette.text, marginBottom: 8 },
  subtitle: { fontSize: 15, color: Palette.textMuted, marginBottom: 24, lineHeight: 21 },
  row: { flexDirection: 'row', gap: 12 },
});
