import React from 'react';
import { StyleSheet, Text, TextInput, TextInputProps, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette } from '@/constants/theme';

type Props = TextInputProps & {
  label: string;
  icon?: keyof typeof Ionicons.glyphMap;
  error?: string;
  right?: React.ReactNode;
};

export function Field({ label, icon, error, right, style, ...input }: Props) {
  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.wrapper, !!error && { borderColor: Palette.danger }]}>
        {icon && <Ionicons name={icon} size={20} color={Palette.textMuted} style={styles.icon} />}
        <TextInput
          accessibilityLabel={label}
          placeholderTextColor={Palette.textFaint}
          style={[styles.input, style]}
          {...input}
        />
        {right}
      </View>
      {!!error && <Text style={styles.error}>{error}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: 18 },
  label: { fontSize: 14, fontWeight: '700', color: Palette.label, marginBottom: 8, marginLeft: 4 },
  wrapper: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: Palette.surface,
    borderWidth: 1.5, borderColor: Palette.border, borderRadius: 16, paddingHorizontal: 16, height: 56,
  },
  icon: { marginRight: 12 },
  input: { flex: 1, fontSize: 16, color: Palette.text, fontWeight: '500' },
  error: { color: Palette.danger, fontSize: 12, marginTop: 6, marginLeft: 4 },
});
