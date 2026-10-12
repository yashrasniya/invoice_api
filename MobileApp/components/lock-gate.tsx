import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as LocalAuthentication from 'expo-local-authentication';
import { Button } from '@/components/ui/button';
import { Palette } from '@/constants/theme';
import { usePrefs } from '@/store/prefs';
import { useSession } from '@/store/session';

/** Re-lock after the app has been in the background this long. */
const RELOCK_AFTER_MS = 30_000;

/**
 * Covers the app with a biometric prompt when the user turned the lock on. Mounted above the
 * navigator, so nothing underneath is reachable (or readable in the app switcher) while locked.
 */
export function LockGate({ children }: { children: React.ReactNode }) {
  const enabled = usePrefs((s) => s.biometricLock);
  const signedIn = useSession((s) => s.status === 'signedIn');
  const active = enabled && signedIn;

  const [locked, setLocked] = useState(true);
  const [busy, setBusy] = useState(false);
  const leftAt = useRef<number | null>(null);
  const prompting = useRef(false);

  const unlock = useCallback(async () => {
    if (prompting.current) return;
    prompting.current = true;
    setBusy(true);
    try {
      const res = await LocalAuthentication.authenticateAsync({
        promptMessage: 'Unlock Invoice Pro',
        cancelLabel: 'Cancel',
        // allow the device passcode as a fallback so a failed face/finger never locks the user out
        disableDeviceFallback: false,
      });
      if (res.success) setLocked(false);
    } finally {
      prompting.current = false;
      setBusy(false);
    }
  }, []);

  // lock (and prompt) whenever the feature becomes relevant: app start with it on, or just signed in
  useEffect(() => {
    if (active) { setLocked(true); unlock(); } else setLocked(false);
  }, [active, unlock]);

  useEffect(() => {
    if (!active) return;
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'background') leftAt.current = Date.now();
      if (state === 'active' && leftAt.current && Date.now() - leftAt.current > RELOCK_AFTER_MS) {
        leftAt.current = null;
        setLocked(true);
        unlock();
      }
    });
    return () => sub.remove();
  }, [active, unlock]);

  if (active && locked) {
    return (
      <View style={styles.screen}>
        <Ionicons name="lock-closed" size={56} color={Palette.primary} />
        <Text style={styles.title}>Invoice Pro is locked</Text>
        <Text style={styles.sub}>Unlock to see your invoices.</Text>
        <Button title="Unlock" onPress={unlock} loading={busy} style={{ alignSelf: 'stretch', marginTop: 12 }} />
        <Button title="Sign out" variant="outline" onPress={() => useSession.getState().signOut()} style={{ alignSelf: 'stretch' }} />
      </View>
    );
  }
  return <>{children}</>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 12, backgroundColor: Palette.white },
  title: { fontSize: 22, fontWeight: '800', color: Palette.text, marginTop: 8 },
  sub: { fontSize: 15, color: Palette.textMuted },
});
