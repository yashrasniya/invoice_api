import React, { useRef, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Button } from '@/components/ui/button';
import { Field, type FieldRef } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import { login } from '@/services/auth';
import { GoogleButton, googleSignInConfigured } from '@/components/google-button';
import { PhoneButton, phoneSignInAvailable } from '@/components/phone-button';
import { AuthHeader, BrandFooter, OrDivider } from '@/components/auth-bits';
import { parseInviteToken } from '@/lib/invite-link';
import { useSession } from '@/store/session';

export default function LoginScreen() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const [inviteText, setInviteText] = useState('');
  const [errors, setErrors] = useState<{ username?: string; password?: string; form?: string }>({});
  const passwordRef = useRef<FieldRef>(null);
  const socialCount = Number(googleSignInConfigured) + Number(phoneSignInAvailable);

  const handleLogin = async () => {
    const e: typeof errors = {};
    if (!username.trim()) e.username = 'Enter your email or username';
    if (!password) e.password = 'Enter your password';
    setErrors(e);
    if (e.username || e.password) return;
    setLoading(true);
    try {
      const { token, user } = await login(username.trim(), password);
      await useSession.getState().signIn(token, user);
      // the root layout's guards swap in the signed-in screens
    } catch (e) {
      setErrors({ form: errorMessage(e, 'Invalid username or password.') });
    } finally {
      setLoading(false);
    }
  };

  const promptInvite = () => {
    if (Platform.OS === 'ios') {
      Alert.prompt('Join with an invite', 'Paste the invitation link from your email.', (text) => {
        const t = parseInviteToken(text ?? '');
        if (t) router.push(`/invite/${t}`); else Alert.alert('Not an invite link', 'That does not look like an invitation link.');
      });
    } else {
      setShowInvite(true);
    }
  };

  const submitInvite = () => {
    const t = parseInviteToken(inviteText);
    if (!t) return Alert.alert('Not an invite link', 'That does not look like an invitation link.');
    setShowInvite(false);
    router.push(`/invite/${t}`);
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
        <AuthHeader heading="Sign in to continue" />

        {!!errors.form && (
          <View style={styles.banner} accessibilityLiveRegion="polite">
            <Ionicons name="alert-circle" size={18} color={Palette.danger} />
            <Text style={styles.bannerText}>{errors.form}</Text>
          </View>
        )}
        <Field
          label="Email or username" icon="person-outline" placeholder="name@company.com"
          value={username} onChangeText={(v) => { setUsername(v); setErrors((x) => ({ ...x, username: undefined, form: undefined })); }}
          autoCapitalize="none" autoCorrect={false} autoComplete="username" textContentType="username"
          keyboardType="email-address" returnKeyType="next" blurOnSubmit={false}
          onSubmitEditing={() => passwordRef.current?.focus()} error={errors.username}
        />
        <Field
          ref={passwordRef} label="Password" icon="lock-closed-outline" placeholder="Your password"
          value={password} onChangeText={(v) => { setPassword(v); setErrors((x) => ({ ...x, password: undefined, form: undefined })); }}
          secureTextEntry={!showPassword} autoCapitalize="none" autoComplete="current-password"
          textContentType="password" onSubmitEditing={handleLogin} returnKeyType="go" error={errors.password}
          right={
            <TouchableOpacity
              onPress={() => setShowPassword((v) => !v)} hitSlop={12}
              accessibilityRole="button" accessibilityLabel={showPassword ? 'Hide password' : 'Show password'}>
              <Ionicons name={showPassword ? 'eye-off-outline' : 'eye-outline'} size={20} color={Palette.textMuted} />
            </TouchableOpacity>
          }
        />

        <Button title="Sign In" onPress={handleLogin} loading={loading} style={{ marginTop: 4 }} />

        {socialCount > 0 && (
          <>
            <OrDivider />
            <View style={styles.socialRow}>
              {googleSignInConfigured && (
                <View style={styles.socialCell}>
                  <GoogleButton loading={loading} setLoading={setLoading} title={socialCount > 1 ? 'Google' : 'Continue with Google'} />
                </View>
              )}
              {phoneSignInAvailable && (
                <View style={styles.socialCell}>
                  <PhoneButton disabled={loading} title={socialCount > 1 ? 'Phone' : 'Continue with phone'} />
                </View>
              )}
            </View>
          </>
        )}

        <View style={styles.footer}>
          <Text style={styles.footerText}>Don&apos;t have an account?{' '}</Text>
          <TouchableOpacity onPress={() => router.push('/signup')} hitSlop={12} accessibilityRole="link">
            <Text style={styles.link}>Sign Up</Text>
          </TouchableOpacity>
        </View>

        {showInvite && (
          <View style={{ marginTop: 20 }}>
            <Field label="Invitation link" placeholder="Paste the link from your email" value={inviteText}
              onChangeText={setInviteText} autoCapitalize="none" autoCorrect={false} />
            <Button title="Continue" variant="outline" onPress={submitInvite} style={{ height: 48 }} />
          </View>
        )}
        <TouchableOpacity onPress={promptInvite} hitSlop={12} accessibilityRole="link" style={styles.invite}>
          <Text style={styles.inviteText}>Have an invite link?</Text>
        </TouchableOpacity>
        <BrandFooter />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Palette.white },
  scroll: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 48 },
  socialRow: { flexDirection: 'row', gap: 12 },
  socialCell: { flex: 1 },
  banner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: '#fef2f2', borderColor: '#fecaca',
    borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 16,
  },
  bannerText: { flex: 1, color: Palette.danger, fontSize: 14 },
  footer: { flexDirection: 'row', justifyContent: 'center', marginTop: 28 },
  footerText: { color: Palette.textMuted, fontSize: 15 },
  link: { color: Palette.primary, fontSize: 15, fontWeight: '700' },
  invite: { alignItems: 'center', marginTop: 20, paddingVertical: 8 },
  inviteText: { color: Palette.textMuted, fontSize: 14, fontWeight: '600' },
});
