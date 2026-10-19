import React from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';
import Constants from 'expo-constants';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { Palette } from '@/constants/theme';

const TERMS_URL = process.env.EXPO_PUBLIC_TERMS_URL;
const PRIVACY_URL = process.env.EXPO_PUBLIC_PRIVACY_URL;

/** Logo, "Orvine Invoice" wordmark and tagline, then the screen's own heading — shared by login and signup. */
export function AuthHeader({ heading }: { heading: string }) {
  return (
    <View style={styles.header}>
      <LinearGradient colors={[Palette.primary, Palette.primaryAlt]} style={styles.logo}>
        <Ionicons name="receipt" size={30} color="white" />
      </LinearGradient>
      <Text style={styles.brand} accessibilityRole="header">
        Orvine<Text style={styles.brandLight}> Invoice</Text>
      </Text>
      <Text style={styles.tagline}>GST invoices in seconds</Text>
      <Text style={styles.heading}>{heading}</Text>
    </View>
  );
}

/** Small "Orvine Invoice · v1.0.0" line for the bottom of the auth screens. */
export function BrandFooter() {
  const version = Constants.expoConfig?.version;
  return <Text style={styles.footerBrand}>Orvine Invoice{version ? ` · v${version}` : ''}</Text>;
}

/** Thin "── or ──" separator between the password form and the social buttons. */
export function OrDivider() {
  return (
    <View style={styles.divider} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <View style={styles.rule} />
      <Text style={styles.dividerText}>or</Text>
      <View style={styles.rule} />
    </View>
  );
}

/** "By continuing you agree to…" — the links render only when EXPO_PUBLIC_TERMS_URL / _PRIVACY_URL are set. */
export function LegalNote() {
  const link = (label: string, url?: string) =>
    url ? <Text style={styles.legalLink} onPress={() => Linking.openURL(url)} accessibilityRole="link">{label}</Text> : label;
  return (
    <Text style={styles.legal}>
      By creating an account you agree to our {link('Terms of Service', TERMS_URL)} and {link('Privacy Policy', PRIVACY_URL)}.
    </Text>
  );
}

const styles = StyleSheet.create({
  header: { alignItems: 'center', marginBottom: 28 },
  logo: { width: 60, height: 60, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  brand: { fontSize: 24, fontWeight: '800', color: Palette.text, letterSpacing: -0.3 },
  brandLight: { fontWeight: '400', color: Palette.textMuted },
  tagline: { fontSize: 13, color: Palette.textMuted, marginTop: 2 },
  heading: { fontSize: 17, fontWeight: '700', color: Palette.text, marginTop: 20 },
  footerBrand: { fontSize: 11, color: Palette.textMuted, textAlign: 'center', marginTop: 20 },
  divider: { flexDirection: 'row', alignItems: 'center', marginVertical: 20 },
  rule: { flex: 1, height: 1, backgroundColor: Palette.border },
  dividerText: { marginHorizontal: 12, color: Palette.textMuted, fontSize: 13, fontWeight: '600' },
  legal: { marginTop: 16, fontSize: 12, lineHeight: 18, color: Palette.textMuted, textAlign: 'center' },
  legalLink: { color: Palette.primary, fontWeight: '600' },
});
