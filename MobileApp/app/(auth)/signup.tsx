import React, { useEffect, useRef, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Button } from '@/components/ui/button';
import { Field, type FieldRef } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { apiErrorCode, errorMessage, fieldErrors } from '@/services/api';
import { mobileDigits } from '@/lib/mobile';
import { passwordFeedback } from '@/lib/password';
import { type PhoneChallenge, startPhoneSignIn, toE164 } from '@/lib/phone-auth';
import { GoogleButton, googleSignInConfigured } from '@/components/google-button';
import { PhoneButton, phoneSignInAvailable } from '@/components/phone-button';
import { AuthHeader, BrandFooter, LegalNote, OrDivider } from '@/components/auth-bits';
import { register } from '@/services/auth';
import { useSession } from '@/store/session';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const RESEND_SECONDS = 30;
/** Server field names → the form's field names (the form has one "Full name" box). */
const FORM_FIELD: Record<string, string> = { first_name: 'full_name', last_name: 'full_name' };

export default function SignupScreen() {
  const [form, setForm] = useState({ full_name: '', email: '', mobile_number: '', password: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [emailTaken, setEmailTaken] = useState(false);
  // second step: the SMS code (only in builds where Firebase phone auth is available)
  const [challenge, setChallenge] = useState<PhoneChallenge | null>(null);
  const [code, setCode] = useState('');
  const [wait, setWait] = useState(0);
  const emailRef = useRef<FieldRef>(null);
  const mobileRef = useRef<FieldRef>(null);
  const passwordRef = useRef<FieldRef>(null);
  const socialCount = Number(googleSignInConfigured) + Number(phoneSignInAvailable);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const set = (k: keyof typeof form) => (v: string) => {
    setForm((f) => ({ ...f, [k]: v }));
    setErrors((e) => (e[k] ? { ...e, [k]: '' } : e)); // clear a field's error as soon as the user edits it
    if (k === 'email') setEmailTaken(false);
  };

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.full_name.trim()) e.full_name = 'Required';
    if (!EMAIL_RE.test(form.email.trim())) e.email = 'Enter a valid email';
    if (!toE164(form.mobile_number)) e.mobile_number = 'Enter a valid 10 digit mobile number';
    if (form.password.length < 8) e.password = 'At least 8 characters';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  /** One request creates the account and signs in; `proof` is the Firebase token when the number was verified. */
  const createAccount = async (proof: string | null) => {
    setLoading(true);
    try {
      // one "Full name" box; the server stores first/last and derives the username from the email
      const [first_name, ...rest] = form.full_name.trim().split(/\s+/);
      const { token, user } = await register({
        first_name,
        last_name: rest.join(' '),
        email: form.email.trim(),
        mobile_number: form.mobile_number,
        password: form.password,
        ...(proof ? { phone_id_token: proof } : {}),
      });
      await useSession.getState().signIn(token, user);
      // new accounts have no company yet; the root layout routes them to company setup
    } catch (e) {
      const raw = fieldErrors(e);
      if (raw.phone_id_token) {
        Alert.alert('Could not verify your number', raw.phone_id_token);
        setChallenge(null);
      }
      const mapped: Record<string, string> = {};
      for (const [k, v] of Object.entries(raw)) if (k !== 'phone_id_token') mapped[FORM_FIELD[k] ?? k] = v;
      if (Object.keys(mapped).length > 0) {
        setErrors(mapped);
        setEmailTaken(apiErrorCode(e) === 'email_exists');
        setChallenge(null); // back to the form so the message sits next to the field it is about
      } else if (!raw.phone_id_token) {
        Alert.alert('Sign up failed', errorMessage(e));
      }
    } finally {
      setLoading(false);
    }
  };

  const sendCode = async () => {
    const number = toE164(form.mobile_number)!;
    setLoading(true);
    try {
      setChallenge(await startPhoneSignIn(number));
      setCode('');
      setWait(RESEND_SECONDS);
    } catch (e) {
      // an SMS outage or a build without Firebase config must not stop someone from signing up
      Alert.alert('Could not send the code', (e as Error).message, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Continue without verifying', onPress: () => createAccount(null) },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSignup = () => {
    if (!validate()) return;
    if (phoneSignInAvailable) sendCode();
    else createAccount(null);
  };

  const verifyAndCreate = async () => {
    if (!challenge) return;
    if (code.trim().length < 6) return Alert.alert('Enter the code', 'Type the 6 digit code from the SMS.');
    setLoading(true);
    try {
      const proof = await challenge.confirm(code);
      await createAccount(proof);
    } catch (e) {
      Alert.alert('Could not verify', (e as Error).message);
      setLoading(false);
    }
  };

  const pw = form.password ? passwordFeedback(form.password, { email: form.email, name: form.full_name }) : null;

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
        <TouchableOpacity style={styles.back} onPress={() => router.back()} accessibilityRole="button" accessibilityLabel="Go back">
          <Ionicons name="arrow-back" size={24} color={Palette.text} />
        </TouchableOpacity>
        <AuthHeader heading="Create your account" />

        {!challenge ? (
          <>
        <Field label="Full name" icon="person-outline" placeholder="Asha Rao" value={form.full_name}
          onChangeText={set('full_name')} autoCapitalize="words" autoComplete="name" textContentType="name"
          returnKeyType="next" blurOnSubmit={false} onSubmitEditing={() => emailRef.current?.focus()} error={errors.full_name} />
        <Field ref={emailRef} label="Email" icon="mail-outline" placeholder="name@company.com" value={form.email}
          onChangeText={set('email')} autoCapitalize="none" autoCorrect={false} keyboardType="email-address"
          autoComplete="email" textContentType="emailAddress" returnKeyType="next" blurOnSubmit={false}
          onSubmitEditing={() => mobileRef.current?.focus()} error={errors.email} />
        {emailTaken && (
          <TouchableOpacity onPress={() => router.replace('/login')} style={styles.signInHint} accessibilityRole="link">
            <Text style={styles.link}>Sign in instead</Text>
          </TouchableOpacity>
        )}
        <Field ref={mobileRef} label="Mobile number" icon="call-outline" placeholder="98765 43210" value={form.mobile_number}
          onChangeText={(t) => set('mobile_number')(mobileDigits(t))} keyboardType="phone-pad" autoComplete="tel" textContentType="telephoneNumber"
          returnKeyType="next" onSubmitEditing={() => passwordRef.current?.focus()} error={errors.mobile_number} />
        <Field ref={passwordRef} label="Password" icon="lock-closed-outline" placeholder="At least 8 characters" value={form.password}
          onChangeText={set('password')} secureTextEntry={!showPassword} autoCapitalize="none" autoComplete="new-password"
          textContentType="newPassword" returnKeyType="go" onSubmitEditing={handleSignup} error={errors.password}
          hint={pw?.message} hintTone={pw?.ok ? 'good' : 'neutral'}
          right={
            <TouchableOpacity
              onPress={() => setShowPassword((v) => !v)} hitSlop={12}
              accessibilityRole="button" accessibilityLabel={showPassword ? 'Hide password' : 'Show password'}>
              <Ionicons name={showPassword ? 'eye-off-outline' : 'eye-outline'} size={20} color={Palette.textMuted} />
            </TouchableOpacity>
          } />

        <Button title={phoneSignInAvailable ? 'Continue' : 'Join Free'} onPress={handleSignup} loading={loading} style={{ marginTop: 4 }} />
        <LegalNote />
          </>
        ) : (
        <>
          <Text style={styles.codeTitle}>Verify your number</Text>
          <Text style={styles.codeSub}>We sent a 6 digit code to +91 {form.mobile_number}.</Text>
          <Field label="Verification code" icon="keypad-outline" placeholder="123456" value={code}
            onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad"
            autoComplete="sms-otp" textContentType="oneTimeCode" maxLength={6} onSubmitEditing={verifyAndCreate} />
          <Button title="Verify and join" onPress={verifyAndCreate} loading={loading} style={{ marginTop: 4 }} />
          <View style={styles.codeRow}>
            <TouchableOpacity onPress={() => setChallenge(null)} hitSlop={12}><Text style={styles.link}>Change number</Text></TouchableOpacity>
            <TouchableOpacity onPress={sendCode} disabled={wait > 0 || loading} hitSlop={12}>
              <Text style={[styles.link, (wait > 0 || loading) && { opacity: 0.4 }]}>{wait > 0 ? `Resend in ${wait}s` : 'Resend code'}</Text>
            </TouchableOpacity>
          </View>
          <TouchableOpacity onPress={() => createAccount(null)} disabled={loading} style={styles.later} hitSlop={12}>
            <Text style={styles.laterText}>Verify later</Text>
          </TouchableOpacity>
        </>
        )}

        {socialCount > 0 && !challenge && (
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
          <Text style={styles.footerText}>Already have an account? </Text>
          <TouchableOpacity onPress={() => router.replace('/login')} hitSlop={12} accessibilityRole="link">
            <Text style={styles.link}>Sign In</Text>
          </TouchableOpacity>
        </View>
        <BrandFooter />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Palette.white },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingTop: 48, paddingBottom: 40 },
  back: { width: 44, height: 44, borderRadius: 12, backgroundColor: Palette.surface, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  signInHint: { alignSelf: 'flex-start', marginTop: -10, marginBottom: 14, marginLeft: 4 },
  codeTitle: { fontSize: 20, fontWeight: '800', color: Palette.text, marginBottom: 6 },
  codeSub: { fontSize: 15, color: Palette.textMuted, marginBottom: 20, lineHeight: 21 },
  codeRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 20 },
  later: { alignItems: 'center', marginTop: 20 },
  laterText: { color: Palette.textMuted, fontSize: 14, fontWeight: '600' },
  socialRow: { flexDirection: 'row', gap: 12 },
  socialCell: { flex: 1 },
  footer: { flexDirection: 'row', justifyContent: 'center', marginTop: 28 },
  footerText: { color: Palette.textMuted, fontSize: 15 },
  link: { color: Palette.primary, fontSize: 15, fontWeight: '700' },
});
