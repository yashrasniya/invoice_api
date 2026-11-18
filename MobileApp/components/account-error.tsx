import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/button';
import { useThemedStyles, type Theme } from '@/hooks/use-theme';
import { useSession } from '@/store/session';

/** Signed in, but the account could not be loaded and there is nothing saved to fall back on. */
export function AccountError() {
  const styles = useThemedStyles(makeStyles);
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    await useSession.getState().bootstrap();
    setBusy(false);
  };
  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Couldn&apos;t load your account</Text>
      <Text style={styles.sub}>Check your internet connection and try again.</Text>
      <Button title="Try again" onPress={retry} loading={busy} style={{ alignSelf: 'stretch' }} />
      <Button title="Sign out" variant="outline" onPress={() => useSession.getState().signOut()} style={{ alignSelf: 'stretch' }} />
    </View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  screen: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 14, backgroundColor: t.surface },
  title: { fontSize: 22, fontWeight: '800', color: t.text, textAlign: 'center' },
  sub: { fontSize: 15, color: t.textMuted, textAlign: 'center' },
});
