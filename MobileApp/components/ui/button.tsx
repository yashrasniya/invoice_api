import React from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, ViewStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { Palette } from '@/constants/theme';

type Props = {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  variant?: 'primary' | 'outline' | 'danger';
  icon?: keyof typeof Ionicons.glyphMap;
  style?: ViewStyle;
};

export function Button({ title, onPress, loading, disabled, variant = 'primary', icon, style }: Props) {
  const inactive = loading || disabled;
  const a11y = { accessibilityRole: 'button' as const, accessibilityLabel: title, accessibilityState: { disabled: !!inactive, busy: !!loading } };
  const label = (color: string) => (
    loading ? <ActivityIndicator color={color} /> : (
      <>
        {icon && <Ionicons name={icon} size={20} color={color} style={{ marginRight: 8 }} />}
        <Text style={[styles.label, { color }]}>{title}</Text>
      </>
    )
  );

  if (variant === 'primary') {
    return (
      <TouchableOpacity {...a11y} onPress={onPress} disabled={inactive} style={[styles.base, inactive && styles.inactive, style]}>
        <LinearGradient colors={[Palette.primary, Palette.primaryAlt]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.fill}>
          {label(Palette.white)}
        </LinearGradient>
      </TouchableOpacity>
    );
  }
  const color = variant === 'danger' ? Palette.danger : Palette.primary;
  return (
    <TouchableOpacity
      {...a11y}
      onPress={onPress}
      disabled={inactive}
      style={[styles.base, styles.center, { borderWidth: 1.5, borderColor: variant === 'danger' ? '#fecaca' : Palette.border }, inactive && styles.inactive, style]}>
      {label(color)}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: { height: 56, borderRadius: 16, overflow: 'hidden' },
  // `fill` is for the gradient inside the primary button; the outline/danger touchables use `center`
  // because flex:1 on a fixed-height control collapses it to nothing inside an auto-height column
  fill: { flex: 1, alignItems: 'center', justifyContent: 'center', flexDirection: 'row' },
  center: { alignItems: 'center', justifyContent: 'center', flexDirection: 'row' },
  label: { fontSize: 16, fontWeight: '700' },
  inactive: { opacity: 0.6 },
});
