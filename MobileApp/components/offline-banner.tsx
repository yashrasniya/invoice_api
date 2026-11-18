import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useThemedStyles, type Theme } from '@/hooks/use-theme';

/** Thin strip under the status bar while the phone has no connection. */
export function OfflineBanner() {
  const styles = useThemedStyles(makeStyles);
  const [offline, setOffline] = useState(false);
  const insets = useSafeAreaInsets();

  useEffect(() => {
    // isInternetReachable is null until probed; only treat an explicit false as offline
    const unsub = NetInfo.addEventListener((s) => setOffline(s.isConnected === false || s.isInternetReachable === false));
    return unsub;
  }, []);

  if (!offline) return null;
  return (
    <View style={[styles.bar, { paddingTop: insets.top + 4 }]} accessibilityRole="alert" accessibilityLiveRegion="polite">
      <Text style={styles.text}>You&apos;re offline — showing saved data</Text>
    </View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  bar: { backgroundColor: t.warningText, paddingBottom: 6, alignItems: 'center' },
  text: { color: t.onPrimary, fontSize: 12, fontWeight: '700' },
});
