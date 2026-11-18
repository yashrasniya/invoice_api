import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import type { ThemeMode } from '@/constants/theme';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { usePrefs } from '@/store/prefs';

const OPTIONS: { mode: ThemeMode; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { mode: 'system', label: 'System', icon: 'phone-portrait-outline' },
  { mode: 'light', label: 'Light', icon: 'sunny-outline' },
  { mode: 'dark', label: 'Dark', icon: 'moon-outline' },
];

/** System / Light / Dark selector. The choice is saved on this device and applies immediately. */
export function ThemeModePicker() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const setThemeMode = usePrefs((s) => s.setThemeMode);

  return (
    <View>
      <Text style={styles.title}>Appearance</Text>
      <View style={styles.row} accessibilityRole="radiogroup">
        {OPTIONS.map((o) => {
          const active = theme.mode === o.mode;
          return (
            <Pressable
              key={o.mode}
              onPress={() => setThemeMode(o.mode)}
              accessibilityRole="radio"
              accessibilityLabel={`${o.label} theme`}
              accessibilityState={{ selected: active }}
              style={[styles.option, active && styles.optionActive]}>
              <Ionicons name={o.icon} size={20} color={active ? theme.primary : theme.textMuted} />
              <Text style={[styles.label, active && styles.labelActive]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
      {theme.mode === 'system' && <Text style={styles.note}>Follows your phone&apos;s light or dark setting.</Text>}
    </View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  title: { color: t.label, fontSize: 14, fontWeight: '800', marginTop: 32, marginBottom: 8 },
  row: { flexDirection: 'row', gap: 10 },
  option: {
    flex: 1, alignItems: 'center', gap: 6, paddingVertical: 14, borderRadius: 14,
    backgroundColor: t.surface, borderWidth: 1.5, borderColor: t.border,
  },
  optionActive: { borderColor: t.primary, backgroundColor: t.primarySoft },
  label: { color: t.textMuted, fontSize: 13, fontWeight: '700' },
  labelActive: { color: t.primary },
  note: { color: t.textMuted, fontSize: 12, marginTop: 8 },
});
