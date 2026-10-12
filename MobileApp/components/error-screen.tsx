import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/button';
import { Palette } from '@/constants/theme';

/** Friendly fallback for an unexpected render error. Shows the message only in development. */
export function ErrorScreen({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Something went wrong</Text>
      <Text style={styles.sub}>The app hit an unexpected problem. You can try again — your data is safe.</Text>
      {__DEV__ && <Text style={styles.dev}>{error.message}</Text>}
      <Button title="Try again" onPress={retry} style={{ alignSelf: 'stretch' }} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 14, backgroundColor: Palette.white },
  title: { fontSize: 22, fontWeight: '800', color: Palette.text },
  sub: { fontSize: 15, color: Palette.textMuted, textAlign: 'center', lineHeight: 21 },
  dev: { fontSize: 12, color: Palette.danger, textAlign: 'center' },
});
