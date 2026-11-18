import React from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';
import Constants from 'expo-constants';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';

const TERMS_URL = process.env.EXPO_PUBLIC_TERMS_URL;
const PRIVACY_URL = process.env.EXPO_PUBLIC_PRIVACY_URL;

/** Logo, "Orvine Invoice" wordmark and tagline, then the screen's own heading — shared by login and signup. */
export function AuthHeader({ heading }: { heading: string }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.header}>
      <LinearGradient colors={[theme.primary, theme.accent]} style={styles.logo}>
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
  const styles = useThemedStyles(makeStyles);
  const version = Constants.expoConfig?.version;
  return <Text style={styles.footerBrand}>Orvine Invoice{version ? ` · v${version}` : ''}</Text>;
}

/** Thin "── or ──" separator between the password form and the social buttons. */
export function OrDivider() {
  const styles = useThemedStyles(makeStyles);
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
  const styles = useThemedStyles(makeStyles);
  const link = (label: string, url?: string) =>
    url ? <Text style={styles.legalLink} onPress={() => Linking.openURL(url)} accessibilityRole="link">{label}</Text> : label;
  return (
    <Text style={styles.legal}>
      By creating an account you agree to our {link('Terms of Service', TERMS_URL)} and {link('Privacy Policy', PRIVACY_URL)}.
    </Text>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  header: { alignItems: 'center', marginBottom: 28 },
  logo: { width: 60, height: 60, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  brand: { fontSize: 24, fontWeight: '800', color: t.text, letterSpacing: -0.3 },
  brandLight: { fontWeight: '400', color: t.textMuted },
  tagline: { fontSize: 13, color: t.textMuted, marginTop: 2 },
  heading: { fontSize: 17, fontWeight: '700', color: t.text, marginTop: 20 },
  footerBrand: { fontSize: 11, color: t.textMuted, textAlign: 'center', marginTop: 20 },
  divider: { flexDirection: 'row', alignItems: 'center', marginVertical: 20 },
  rule: { flex: 1, height: 1, backgroundColor: t.border },
  dividerText: { marginHorizontal: 12, color: t.textMuted, fontSize: 13, fontWeight: '600' },
  legal: { marginTop: 16, fontSize: 12, lineHeight: 18, color: t.textMuted, textAlign: 'center' },
  legalLink: { color: t.primary, fontWeight: '600' },
});
