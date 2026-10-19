import React, { useState } from 'react';
import { Alert, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import { fetchProfile, resendVerification } from '@/services/auth';
import { useSession } from '@/store/session';

/**
 * Soft reminder (not a gate) for accounts whose email was never confirmed. "I've verified" re-reads the profile so
 * the banner disappears without restarting the app.
 */
export function VerifyEmailBanner() {
  const user = useSession((s) => s.user);
  const [busy, setBusy] = useState(false);
  // only a definite `false` counts: an older server that doesn't report the flag must not nag everyone
  if (!user || !user.email || user.email_verified !== false) return null;

  const resend = async () => {
    setBusy(true);
    try {
      const r = await resendVerification();
      Alert.alert(r.email_verified ? 'Already verified' : 'Email sent', r.email_verified ? 'Your email is confirmed.' : `We sent a link to ${r.sent_to}.`);
    } catch (e) {
      Alert.alert('Could not send', errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const check = async () => {
    setBusy(true);
    try {
      const fresh = await fetchProfile();
      useSession.getState().setUser(fresh);
      if (!fresh.email_verified) Alert.alert('Not verified yet', 'Open the link in the email we sent, then check again.');
    } catch (e) {
      Alert.alert('Could not check', errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Confirm your email</Text>
      <Text style={styles.body}>We sent a link to {user.email}. It keeps your account safe and lets you recover it.</Text>
      <View style={styles.row}>
        <TouchableOpacity onPress={resend} disabled={busy} hitSlop={10} accessibilityRole="button">
          <Text style={[styles.link, busy && { opacity: 0.4 }]}>Resend email</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={check} disabled={busy} hitSlop={10} accessibilityRole="button">
          <Text style={[styles.link, busy && { opacity: 0.4 }]}>I&apos;ve verified</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: '#fffbeb', borderColor: '#fde68a', borderWidth: 1, borderRadius: 16, padding: 14, marginBottom: 16 },
  title: { fontSize: 15, fontWeight: '800', color: '#92400e' },
  body: { fontSize: 13, color: '#92400e', marginTop: 4, lineHeight: 18 },
  row: { flexDirection: 'row', gap: 20, marginTop: 10 },
  link: { color: Palette.primary, fontSize: 14, fontWeight: '700' },
});
