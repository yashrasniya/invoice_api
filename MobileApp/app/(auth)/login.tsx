import React, { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import { login } from '@/services/auth';
import { parseInviteToken } from '@/lib/invite-link';
import { useSession } from '@/store/session';

export default function LoginScreen() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const [inviteText, setInviteText] = useState('');

  const handleLogin = async () => {
    if (!username.trim() || !password) {
      Alert.alert('Missing details', 'Please enter both username and password.');
      return;
    }
    setLoading(true);
    try {
      const { token, user } = await login(username.trim(), password);
      await useSession.getState().signIn(token, user);
      // the root layout's guards swap in the signed-in screens
    } catch (e) {
      Alert.alert('Login failed', errorMessage(e, 'Invalid username or password.'));
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
        <View style={styles.header}>
          <LinearGradient colors={[Palette.primary, Palette.primaryAlt]} style={styles.logo}>
            <Ionicons name="receipt" size={40} color="white" />
          </LinearGradient>
          <Text style={styles.title}>Welcome Back</Text>
          <Text style={styles.subtitle}>Sign in to your Invoice Pro account</Text>
        </View>

        <Field
          label="Username" icon="person-outline" placeholder="Your username"
          value={username} onChangeText={setUsername} autoCapitalize="none" autoCorrect={false}
        />
        <Field
          label="Password" icon="lock-closed-outline" placeholder="••••••••"
          value={password} onChangeText={setPassword} secureTextEntry={!showPassword}
          autoCapitalize="none" onSubmitEditing={handleLogin} returnKeyType="go"
          right={
            <TouchableOpacity onPress={() => setShowPassword((v) => !v)} hitSlop={10}>
              <Ionicons name={showPassword ? 'eye-off-outline' : 'eye-outline'} size={20} color={Palette.textMuted} />
            </TouchableOpacity>
          }
        />

        <Button title="Sign In" onPress={handleLogin} loading={loading} style={{ marginTop: 12 }} />

        {showInvite && (
          <View style={{ marginTop: 20 }}>
            <Field label="Invitation link" placeholder="Paste the link from your email" value={inviteText}
              onChangeText={setInviteText} autoCapitalize="none" autoCorrect={false} />
            <Button title="Continue" variant="outline" onPress={submitInvite} style={{ height: 48 }} />
          </View>
        )}
        <TouchableOpacity onPress={promptInvite} style={{ alignItems: 'center', marginTop: 20 }}>
          <Text style={styles.link}>Have an invite link?</Text>
        </TouchableOpacity>

        <View style={styles.footer}>
          <Text style={styles.footerText}>Don&apos;t have an account?{' '}</Text>
          <TouchableOpacity onPress={() => router.push('/signup')}>
            <Text style={styles.link}>Sign Up</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Palette.white },
  scroll: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 40 },
  header: { alignItems: 'center', marginBottom: 36 },
  logo: { width: 80, height: 80, borderRadius: 24, alignItems: 'center', justifyContent: 'center', marginBottom: 20 },
  title: { fontSize: 28, fontWeight: '800', color: Palette.text, marginBottom: 8 },
  subtitle: { fontSize: 16, color: Palette.textMuted, textAlign: 'center' },
  footer: { flexDirection: 'row', justifyContent: 'center', marginTop: 28 },
  footerText: { color: Palette.textMuted, fontSize: 15 },
  link: { color: Palette.primary, fontSize: 15, fontWeight: '700' },
});
