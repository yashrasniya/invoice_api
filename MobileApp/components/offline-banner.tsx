import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Palette } from '@/constants/theme';

/** Thin strip under the status bar while the phone has no connection. */
export function OfflineBanner() {
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

const styles = StyleSheet.create({
  bar: { backgroundColor: '#92400e', paddingBottom: 6, alignItems: 'center' },
  text: { color: Palette.white, fontSize: 12, fontWeight: '700' },
});
