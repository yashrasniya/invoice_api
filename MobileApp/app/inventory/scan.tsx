import React, { useRef, useState } from 'react';
import { ActivityIndicator, Alert, StyleSheet, Text, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Stack, router } from 'expo-router';
import { Button } from '@/components/ui/button';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import { findBySku } from '@/services/inventory';

export default function ScanScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [looking, setLooking] = useState(false);
  const busy = useRef(false); // the scanner fires many events per code; handle one at a time

  const onScan = async ({ data }: { data: string }) => {
    if (busy.current) return;
    busy.current = true;
    setLooking(true);
    const code = data.trim();
    try {
      const hit = await findBySku(code);
      if (hit) {
        router.replace(`/inventory/${hit.id}`);
        return;
      }
      Alert.alert('New product', `No product with SKU "${code}". Add it now?`, [
        { text: 'Scan again', style: 'cancel', onPress: () => { busy.current = false; setLooking(false); } },
        { text: 'Add product', onPress: () => router.replace(`/inventory/new?sku=${encodeURIComponent(code)}`) },
      ], { cancelable: false });
    } catch (e) {
      Alert.alert('Lookup failed', errorMessage(e), [{ text: 'OK', onPress: () => { busy.current = false; setLooking(false); } }]);
    }
  };

  if (!permission) return <View style={styles.center}><ActivityIndicator color={Palette.primary} /></View>;

  if (!permission.granted) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: 'Scan barcode' }} />
        <Text style={styles.msg}>Camera access is needed to scan product barcodes.</Text>
        <Button title={permission.canAskAgain ? 'Allow camera' : 'Open settings to allow'} onPress={requestPermission} style={{ alignSelf: 'stretch' }} />
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      <Stack.Screen options={{ title: 'Scan barcode' }} />
      <CameraView
        style={styles.flex}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ['ean13', 'ean8', 'upc_a', 'upc_e', 'code128', 'code39', 'qr'] }}
        onBarcodeScanned={onScan}
      />
      <View style={styles.frame} pointerEvents="none" />
      <View style={styles.hint}>
        {looking ? <ActivityIndicator color="white" /> : <Text style={styles.hintText}>Point the camera at a barcode</Text>}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: 'black' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: Palette.white, gap: 16 },
  msg: { fontSize: 16, color: Palette.text, textAlign: 'center' },
  frame: { position: 'absolute', top: '30%', left: '12%', right: '12%', height: 180, borderWidth: 3, borderColor: 'white', borderRadius: 16 },
  hint: { position: 'absolute', bottom: 60, left: 0, right: 0, alignItems: 'center' },
  hintText: { color: 'white', fontSize: 16, fontWeight: '600', backgroundColor: 'rgba(0,0,0,0.55)', paddingHorizontal: 16, paddingVertical: 8, borderRadius: 999, overflow: 'hidden' },
});
