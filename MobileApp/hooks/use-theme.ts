import { useMemo, useSyncExternalStore } from 'react';
import { useColorScheme } from 'react-native';

import { resolveScheme, themes, type ColorScheme, type ThemeMode, type ThemeTokens } from '@/constants/theme';
import { usePrefs } from '@/store/prefs';

export type Theme = ThemeTokens & {
  /** the scheme being shown right now (never `system`) */
  scheme: ColorScheme;
  isDark: boolean;
  /** what the user picked */
  mode: ThemeMode;
};

/**
 * The colors for the current screen. Use this instead of hard-coding hex values (the old `Palette` object is gone):
 *   const theme = useTheme();  <View style={{ backgroundColor: theme.surface }} />
 * See DARK_THEME.md for the token meanings.
 */
export function useTheme(): Theme {
  const mode = usePrefs((s) => s.themeMode);
  const system = useColorScheme();
  const scheme = resolveScheme(mode, system);
  return useMemo(() => ({ ...themes[scheme], scheme, isDark: scheme === 'dark', mode }), [scheme, mode]);
}

/** True once the saved theme choice has been read from storage, so the first paint is not the wrong theme. */
export function useThemeReady(): boolean {
  return useSyncExternalStore(
    (onChange) => usePrefs.persist.onFinishHydration(onChange),
    () => usePrefs.persist.hasHydrated(),
    () => false,
  );
}

/**
 * Styles that depend on the theme. Write `const makeStyles = (t: Theme) => StyleSheet.create({...})` once at
 * module level, then `const styles = useThemedStyles(makeStyles)` in the component.
 */
export function useThemedStyles<T>(make: (t: Theme) => T): T {
  const theme = useTheme();
  return useMemo(() => make(theme), [make, theme]);
}
