import React, { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import { login, register } from '@/services/auth';
import { useSession } from '@/store/session';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function SignupScreen() {
  const [form, setForm] = useState({
    first_name: '', last_name: '', username: '', email: '', mobile_number: '', password: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.first_name.trim()) e.first_name = 'Required';
    if (!form.last_name.trim()) e.last_name = 'Required';
    if (!form.username.trim()) e.username = 'Required';
    if (!EMAIL_RE.test(form.email.trim())) e.email = 'Enter a valid email';
    if (form.mobile_number.replace(/\D/g, '').length < 10) e.mobile_number = 'Enter a valid mobile number';
    if (form.password.length < 8) e.password = 'At least 8 characters';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSignup = async () => {
    if (!validate()) return;
    setLoading(true);
    try {
      const payload = {
        ...form,
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        username: form.username.trim(),
        email: form.email.trim(),
        mobile_number: form.mobile_number.trim(),
      };
      await register(payload);
      const { token, user } = await login(payload.username, payload.password);
      await useSession.getState().signIn(token, user);
      // new accounts have no company yet; the root layout routes them to company setup
    } catch (e) {
      Alert.alert('Sign up failed', errorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
        <TouchableOpacity style={styles.back} onPress={() => router.back()}>
          <Ionicons name="arrow-back" size={24} color={Palette.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Create Account</Text>
        <Text style={styles.subtitle}>Start managing your invoices with ease</Text>

        <View style={styles.row}>
          <View style={styles.half}>
            <Field label="First name" value={form.first_name} onChangeText={set('first_name')} error={errors.first_name} />
          </View>
          <View style={styles.half}>
            <Field label="Last name" value={form.last_name} onChangeText={set('last_name')} error={errors.last_name} />
          </View>
        </View>
        <Field label="Username" icon="person-outline" value={form.username} onChangeText={set('username')}
          autoCapitalize="none" autoCorrect={false} error={errors.username} />
        <Field label="Email" icon="mail-outline" placeholder="name@company.com" value={form.email}
          onChangeText={set('email')} autoCapitalize="none" keyboardType="email-address" error={errors.email} />
        <Field label="Mobile number" icon="call-outline" placeholder="98765 43210" value={form.mobile_number}
          onChangeText={set('mobile_number')} keyboardType="phone-pad" error={errors.mobile_number} />
        <Field label="Password" icon="lock-closed-outline" placeholder="At least 8 characters" value={form.password}
          onChangeText={set('password')} secureTextEntry autoCapitalize="none" error={errors.password} />

        <Button title="Join Free" onPress={handleSignup} loading={loading} style={{ marginTop: 8 }} />

        <View style={styles.footer}>
          <Text style={styles.footerText}>Already have an account? </Text>
          <TouchableOpacity onPress={() => router.replace('/login')}>
            <Text style={styles.link}>Sign In</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Palette.white },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingVertical: 60 },
  back: { width: 44, height: 44, borderRadius: 12, backgroundColor: Palette.surface, alignItems: 'center', justifyContent: 'center', marginBottom: 20 },
  title: { fontSize: 28, fontWeight: '800', color: Palette.text, marginBottom: 8 },
  subtitle: { fontSize: 16, color: Palette.textMuted, marginBottom: 28 },
  row: { flexDirection: 'row', gap: 12 },
  half: { flex: 1 },
  footer: { flexDirection: 'row', justifyContent: 'center', marginTop: 28 },
  footerText: { color: Palette.textMuted, fontSize: 15 },
  link: { color: Palette.primary, fontSize: 15, fontWeight: '700' },
});
