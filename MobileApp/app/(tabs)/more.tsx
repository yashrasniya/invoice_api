import React from 'react';
import { Alert, ScrollView, StyleSheet, Switch, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Palette } from '@/constants/theme';
import * as LocalAuthentication from 'expo-local-authentication';
import { registerForPush, unregisterPush } from '@/lib/push';
import { useMyDrafts } from '@/store/drafts';
import { usePrefs } from '@/store/prefs';
import { useSession } from '@/store/session';

type RowProps = { icon: keyof typeof Ionicons.glyphMap; label: string; hint?: string; onPress: () => void };

function Row({ icon, label, hint, onPress }: RowProps) {
  return (
    <TouchableOpacity style={styles.row} onPress={onPress} accessibilityRole="button" accessibilityLabel={hint ? `${label}, ${hint}` : label}>
      <Ionicons name={icon} size={22} color={Palette.primary} />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        {!!hint && <Text style={styles.rowHint}>{hint}</Text>}
      </View>
      <Ionicons name="chevron-forward" size={18} color={Palette.textFaint} />
    </TouchableOpacity>
  );
}

function SwitchRow({ icon, label, hint, value, onChange }: {
  icon: keyof typeof Ionicons.glyphMap; label: string; hint?: string; value: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <View style={styles.row} accessible accessibilityRole="switch" accessibilityLabel={label} accessibilityState={{ checked: value }}>
      <Ionicons name={icon} size={22} color={Palette.primary} />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        {!!hint && <Text style={styles.rowHint}>{hint}</Text>}
      </View>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: Palette.primary }} />
    </View>
  );
}

export default function MoreScreen() {
  const insets = useSafeAreaInsets();
  const user = useSession((s) => s.user);
  const access = useSession((s) => s.access);
  const plan = access?.subscription?.plan_name ?? access?.subscription?.plan ?? null;


  const drafts = useMyDrafts();
  const biometricLock = usePrefs((p) => p.biometricLock);
  const pushEnabled = usePrefs((p) => p.pushEnabled);

  const toggleLock = async (on: boolean) => {
    if (!on) return usePrefs.getState().setBiometricLock(false);
    const hardware = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    if (!hardware || !enrolled) {
      return Alert.alert('Not available', 'Set up Face ID, a fingerprint or a screen lock in your phone settings first.');
    }
    // prove it works before locking the user behind it
    const res = await LocalAuthentication.authenticateAsync({ promptMessage: 'Confirm to turn on app lock' });
    if (res.success) usePrefs.getState().setBiometricLock(true);
  };

  const togglePush = async (on: boolean) => {
    if (!on) {
      usePrefs.getState().setPushEnabled(false);
      return void unregisterPush();
    }
    const r = await registerForPush();
    if (r.ok) usePrefs.getState().setPushEnabled(true);
    else Alert.alert('Could not turn on notifications', r.message);
  };

  const confirmSignOut = () =>
    Alert.alert('Sign out', drafts.length
      ? `You have ${drafts.length} unsent draft${drafts.length === 1 ? '' : 's'}. They stay on this phone and will be here when you sign in again.`
      : 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign out', style: 'destructive', onPress: () => useSession.getState().signOut() },
    ]);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={{ paddingTop: insets.top + 16, paddingBottom: 32 }}>
      <View style={styles.header}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(user?.first_name?.[0] ?? user?.username?.[0] ?? '?').toUpperCase()}</Text>
        </View>
        <Text style={styles.name}>{user?.name || user?.username}</Text>
        <Text style={styles.sub}>{access?.company_name}{plan ? ` · ${plan}` : ''}</Text>
      </View>

      <Text style={styles.groupTitle}>Business</Text>
      <View style={styles.group}>
        <Row icon="business-outline" label="Vendors" onPress={() => router.push('/vendors')} />
        <Row icon="cart-outline" label="Purchases" hint="Bills & scan with camera" onPress={() => router.push('/purchases')} />
        <Row icon="cube-outline" label="Inventory" hint="Stock, products & barcode scan" onPress={() => router.push('/inventory')} />
        {drafts.length > 0 && (
          <Row icon="cloud-upload-outline" label={`Drafts (${drafts.length})`} hint="Saved offline, waiting to send" onPress={() => router.push('/drafts')} />
        )}
        <Row icon="bar-chart-outline" label="Reports" hint="Sales, GST, cash flow, ledgers" onPress={() => router.push('/reports')} />
      </View>

      <Text style={styles.groupTitle}>Settings</Text>
      <View style={styles.group}>
        <Row icon="logo-whatsapp" label="WhatsApp" hint="Sending number & templates" onPress={() => router.push('/whatsapp')} />
        <Row icon="document-text-outline" label="Invoice templates" hint="Choose your invoice design" onPress={() => router.push('/templates')} />
        <Row icon="list-outline" label="Invoice numbering" onPress={() => router.push('/numbering')} />
        <Row icon="people-outline" label="Team & access" hint="Members, invites, roles" onPress={() => router.push('/team')} />
        <Row icon="card-outline" label="Plan & billing" onPress={() => router.push('/billing')} />
      </View>

      <Text style={styles.groupTitle}>Account</Text>
      <View style={styles.group}>
        <SwitchRow icon="finger-print-outline" label="App lock" hint="Ask for Face ID / fingerprint when opening" value={biometricLock} onChange={toggleLock} />
        <SwitchRow icon="notifications-outline" label="Notifications" hint="Tell me when a scanned bill is ready" value={pushEnabled} onChange={togglePush} />
        <Row icon="person-outline" label="My profile" onPress={() => router.push('/profile')} />
        <Row icon="log-out-outline" label="Sign out" onPress={confirmSignOut} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  header: { alignItems: 'center', paddingHorizontal: 20, marginBottom: 24 },
  avatar: { width: 72, height: 72, borderRadius: 36, backgroundColor: Palette.primary, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  avatarText: { color: Palette.white, fontSize: 28, fontWeight: '800' },
  name: { fontSize: 20, fontWeight: '800', color: Palette.text },
  sub: { fontSize: 14, color: Palette.textMuted, marginTop: 2 },
  groupTitle: { fontSize: 13, fontWeight: '700', color: Palette.textMuted, textTransform: 'uppercase', marginHorizontal: 24, marginBottom: 8 },
  group: { backgroundColor: Palette.white, marginHorizontal: 20, borderRadius: 16, borderWidth: 1, borderColor: Palette.border, marginBottom: 16, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, padding: 16 },
  rowLabel: { fontSize: 16, fontWeight: '600', color: Palette.text },
  rowHint: { fontSize: 12, color: Palette.textMuted, marginTop: 2 },
});
