import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { errorMessage } from '@/services/api';
import { acceptInvite, fetchInvite } from '@/services/auth';
import { useSession } from '@/store/session';

type Info = Awaited<ReturnType<typeof fetchInvite>>;

export default function InviteScreen() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const { token } = useLocalSearchParams<{ token: string }>();
  const [info, setInfo] = useState<Info | null>(null);
  const [invalid, setInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ first_name: '', last_name: '', username: '', password: '' });
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    fetchInvite(token).then(setInfo).catch(() => setInvalid(true));
  }, [token]);

  const accept = async () => {
    if (info?.existing_account && !form.password) {
      Alert.alert('Missing password', 'Enter the password of your existing account.');
      return;
    }
    if (info && !info.existing_account && (!form.username.trim() || form.password.length < 8)) {
      Alert.alert('Missing details', 'Choose a username and a password of at least 8 characters.');
      return;
    }
    setBusy(true);
    try {
      const { token: access, user } = await acceptInvite(token, info?.existing_account ? { password: form.password } : form);
      await useSession.getState().signIn(access, user);
    } catch (e) {
      Alert.alert('Could not accept invite', errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!info && !invalid) {
    return <View style={styles.center}><ActivityIndicator size="large" color={theme.primary} /></View>;
  }
  if (invalid || !info) {
    return (
      <View style={styles.center}>
        <Text style={styles.title}>Invite not valid</Text>
        <Text style={styles.subtitle}>This invitation has expired or was already used. Ask your admin to send a new one.</Text>
        <Button title="Go to sign in" onPress={() => router.replace('/login')} style={{ alignSelf: 'stretch' }} />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.flex}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Join {info.company_name}</Text>
        <Text style={styles.subtitle}>
          You were invited as {info.email}.
          {info.existing_account ? ' Enter your existing account password to add this company to it.' : ' Create your login to continue.'}
        </Text>
        {info.existing_account && (
          <Field label="Password" value={form.password} onChangeText={set('password')} secureTextEntry autoCapitalize="none" />
        )}
        {!info.existing_account && (
          <>
            <Field label="First name" value={form.first_name} onChangeText={set('first_name')} />
            <Field label="Last name" value={form.last_name} onChangeText={set('last_name')} />
            <Field label="Username" value={form.username} onChangeText={set('username')} autoCapitalize="none" autoCorrect={false} />
            <Field label="Password" value={form.password} onChangeText={set('password')} secureTextEntry autoCapitalize="none" />
          </>
        )}
        <Button title="Accept invitation" onPress={accept} loading={busy} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  flex: { flex: 1, backgroundColor: t.surface },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: t.surface },
  scroll: { paddingHorizontal: 24, paddingVertical: 64 },
  title: { fontSize: 26, fontWeight: '800', color: t.text, marginBottom: 8 },
  subtitle: { fontSize: 15, color: t.textMuted, marginBottom: 24, lineHeight: 21 },
});
