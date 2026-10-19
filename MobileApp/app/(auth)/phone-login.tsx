import React, { useEffect, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { router } from 'expo-router';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { mobileDigits } from '@/lib/mobile';
import { PhoneChallenge, startPhoneSignIn, toE164 } from '@/lib/phone-auth';
import { errorMessage } from '@/services/api';
import { phoneLogin } from '@/services/auth';
import { useSession } from '@/store/session';

const RESEND_SECONDS = 30;

export default function PhoneLoginScreen() {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [challenge, setChallenge] = useState<PhoneChallenge | null>(null);
  const [e164, setE164] = useState('');
  const [loading, setLoading] = useState(false);
  const [wait, setWait] = useState(0);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const sendCode = async () => {
    const number = toE164(phone);
    if (!number) return Alert.alert('Invalid number', 'Enter a valid 10 digit mobile number.');
    setLoading(true);
    try {
      setChallenge(await startPhoneSignIn(number));
      setE164(number);
      setCode('');
      setWait(RESEND_SECONDS);
    } catch (e) {
      Alert.alert('Could not send code', (e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const verify = async () => {
    if (!challenge) return;
    if (code.trim().length < 6) return Alert.alert('Enter the code', 'Type the 6 digit code from the SMS.');
    setLoading(true);
    try {
      const idToken = await challenge.confirm(code);
      const { token, user } = await phoneLogin(idToken);
      await useSession.getState().signIn(token, user);
      // the root layout's guards swap in the signed-in screens
    } catch (e) {
      Alert.alert('Sign-in failed', errorMessage(e, (e as Error).message));
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
        <Text style={styles.title}>{challenge ? 'Enter the code' : 'Sign in with phone'}</Text>
        <Text style={styles.subtitle}>
          {challenge ? `We sent a 6 digit code to ${e164}.` : "We'll text you a code to verify your number."}
        </Text>

        {!challenge ? (
          <>
            <Field
              label="Mobile number" icon="call-outline" placeholder="9876543210" value={phone}
              onChangeText={(t) => setPhone(mobileDigits(t))} keyboardType="phone-pad" autoComplete="tel" textContentType="telephoneNumber" onSubmitEditing={sendCode}
            />
            <Button title="Send code" onPress={sendCode} loading={loading} style={{ marginTop: 12 }} />
          </>
        ) : (
          <>
            <Field
              label="Verification code" icon="keypad-outline" placeholder="123456" value={code}
              onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad"
              autoComplete="sms-otp" textContentType="oneTimeCode" maxLength={6} onSubmitEditing={verify}
            />
            <Button title="Verify and sign in" onPress={verify} loading={loading} style={{ marginTop: 12 }} />
            <View style={styles.row}>
              <TouchableOpacity onPress={() => setChallenge(null)}>
                <Text style={styles.link}>Change number</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={sendCode} disabled={wait > 0 || loading}>
                <Text style={[styles.link, (wait > 0 || loading) && { opacity: 0.4 }]}>
                  {wait > 0 ? `Resend in ${wait}s` : 'Resend code'}
                </Text>
              </TouchableOpacity>
            </View>
          </>
        )}

        <TouchableOpacity onPress={() => router.back()} style={{ alignItems: 'center', marginTop: 28 }}>
          <Text style={styles.link}>Back to sign in</Text>
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Palette.white },
  scroll: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 40 },
  title: { fontSize: 26, fontWeight: '800', color: Palette.text, marginBottom: 8, textAlign: 'center' },
  subtitle: { fontSize: 16, color: Palette.textMuted, textAlign: 'center', marginBottom: 28 },
  row: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 20 },
  link: { color: Palette.primary, fontSize: 15, fontWeight: '700' },
});
