import React, { forwardRef, useState } from 'react';
import { StyleSheet, Text, TextInput, TextInputProps, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';

type Props = TextInputProps & {
  label: string;
  icon?: keyof typeof Ionicons.glyphMap;
  error?: string;
  /** Quiet guidance under the box (shown only while there is no error); `hintTone` colours it green when satisfied. */
  hint?: string;
  hintTone?: 'neutral' | 'good';
  right?: React.ReactNode;
};

export type FieldRef = React.ComponentRef<typeof TextInput>;

export const Field = forwardRef<FieldRef, Props>(function Field({ label, icon, error, hint, hintTone, right, style, onFocus, onBlur, ...input }, ref) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const [focused, setFocused] = useState(false);
  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.wrapper, focused && styles.focused, !!error && { borderColor: theme.danger }]}>
        {icon && <Ionicons name={icon} size={20} color={theme.textMuted} style={styles.icon} />}
        <TextInput
          ref={ref}
          accessibilityLabel={label}
          placeholderTextColor={theme.textMuted}
          style={[styles.input, style]}
          onFocus={(e) => { setFocused(true); onFocus?.(e); }}
          onBlur={(e) => { setFocused(false); onBlur?.(e); }}
          {...input}
        />
        {right}
      </View>
      {!!error && <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text>}
      {!error && !!hint && (
        <Text style={[styles.hint, hintTone === 'good' && { color: theme.success }]} accessibilityLiveRegion="polite">{hint}</Text>
      )}
    </View>
  );
});

const makeStyles = (t: Theme) => StyleSheet.create({
  group: { marginBottom: 18 },
  label: { fontSize: 14, fontWeight: '700', color: t.label, marginBottom: 8, marginLeft: 4 },
  wrapper: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: t.isDark ? t.surfaceRaised : t.background,
    borderWidth: 1.5, borderColor: t.border, borderRadius: 16, paddingHorizontal: 16, height: 56,
  },
  focused: { borderColor: t.primary, backgroundColor: t.surface },
  icon: { marginRight: 12 },
  input: { flex: 1, fontSize: 16, color: t.text, fontWeight: '500' },
  error: { color: t.danger, fontSize: 12, marginTop: 6, marginLeft: 4 },
  hint: { color: t.textMuted, fontSize: 12, marginTop: 6, marginLeft: 4 },
});
