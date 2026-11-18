/**
 * Below are the colors that are used in the app. The colors are defined in the light and dark mode.
 * There are many other ways to style your app. For example, [Nativewind](https://www.nativewind.dev/), [Tamagui](https://tamagui.dev/), [unistyles](https://reactnativeunistyles.vercel.app), etc.
 */

import { Platform } from 'react-native';

const tintColorLight = '#4f46e5';
const tintColorDark = '#818cf8';

export const Colors = {
  light: {
    text: '#11181C',
    background: '#fff',
    tint: tintColorLight,
    icon: '#687076',
    tabIconDefault: '#687076',
    tabIconSelected: tintColorLight,
  },
  dark: {
    text: '#e5e9f2',
    background: '#0b1120',
    tint: tintColorDark,
    icon: '#94a3b8',
    tabIconDefault: '#94a3b8',
    tabIconSelected: tintColorDark,
  },
};

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    serif: "Georgia, 'Times New Roman', serif",
    rounded: "'SF Pro Rounded', 'Hiragino Maru Gothic ProN', Meiryo, 'MS PGothic', sans-serif",
    mono: "SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
  },
});

export type ColorScheme = 'light' | 'dark';
/** What the user picked in Profile; `system` follows the phone's setting. */
export type ThemeMode = 'system' | ColorScheme;

/**
 * Semantic color tokens for both themes. See DARK_THEME.md for what each is for.
 * Screens read these through `useTheme()`; never hard-code a hex in a screen.
 */
export type ThemeTokens = {
  // surfaces (dark mode gets depth from lightness: background < surface < surfaceRaised)
  background: string;
  surface: string;
  surfaceRaised: string;
  surfaceMuted: string;
  border: string;
  borderStrong: string;
  overlay: string;
  // text
  text: string;
  textMuted: string;
  textFaint: string;
  textInverse: string;
  label: string;
  // brand
  primary: string;
  primaryPressed: string;
  primarySoft: string;
  onPrimary: string;
  accent: string;
  // indigo hero card (plan / upgrade banners): a solid indigo fill in light, a deep indigo tint in dark
  hero: string;
  onHero: string;
  onHeroMuted: string;
  // status: solid color for text/icons, `*Soft` for the tinted chip/banner background behind it
  success: string;
  successSoft: string;
  danger: string;
  dangerSoft: string;
  warning: string;
  warningSoft: string;
  info: string;
  infoSoft: string;
  neutral: string;
  neutralSoft: string;
  // readable text/border colors to sit on the *Soft backgrounds (deeper shade in light, the bright color in dark)
  primaryText: string;
  primaryBorder: string;
  successText: string;
  successBorder: string;
  dangerText: string;
  dangerBorder: string;
  warningText: string;
  warningBorder: string;
  infoText: string;
  /** spread into a card's style; empty in dark mode where shadows are invisible */
  shadowCard: {
    shadowColor?: string;
    shadowOpacity?: number;
    shadowRadius?: number;
    shadowOffset?: { width: number; height: number };
    elevation?: number;
  };
};

export const lightTheme: ThemeTokens = {
  background: '#f8fafc',
  surface: '#ffffff',
  surfaceRaised: '#ffffff',
  surfaceMuted: '#f1f5f9',
  border: '#e2e8f0',
  borderStrong: '#cbd5e1',
  overlay: 'rgba(15,23,42,0.45)',
  text: '#0f172a',
  textMuted: '#64748b',
  textFaint: '#94a3b8',
  textInverse: '#ffffff',
  label: '#334155',
  primary: '#4f46e5',
  primaryPressed: '#4338ca',
  primarySoft: '#eef2ff',
  onPrimary: '#ffffff',
  accent: '#7c3aed',
  hero: '#4f46e5',
  onHero: '#ffffff',
  onHeroMuted: '#c7d2fe',
  success: '#16a34a',
  successSoft: '#dcfce7',
  danger: '#dc2626',
  dangerSoft: '#fee2e2',
  warning: '#d97706',
  warningSoft: '#fef3c7',
  info: '#2563eb',
  infoSoft: '#dbeafe',
  neutral: '#64748b',
  neutralSoft: '#f1f5f9',
  primaryText: '#3730a3',
  primaryBorder: '#c7d2fe',
  successText: '#166534',
  successBorder: '#86efac',
  dangerText: '#991b1b',
  dangerBorder: '#fecaca',
  warningText: '#92400e',
  warningBorder: '#fde68a',
  infoText: '#1e40af',
  shadowCard: {
    shadowColor: '#0f172a',
    shadowOpacity: 0.06,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
};

export const darkTheme: ThemeTokens = {
  background: '#0b1120',
  surface: '#131c2e',
  surfaceRaised: '#1b2740',
  surfaceMuted: '#0f1729',
  border: '#26324a',
  borderStrong: '#33425f',
  overlay: 'rgba(0,0,0,0.65)',
  text: '#e5e9f2',
  textMuted: '#94a3b8',
  textFaint: '#64748b',
  textInverse: '#0b1120',
  label: '#cbd5e1',
  primary: '#818cf8',
  primaryPressed: '#6366f1',
  primarySoft: 'rgba(129,140,248,0.16)',
  onPrimary: '#0b1120',
  accent: '#a78bfa',
  hero: '#1c2350',
  onHero: '#e5e9f2',
  onHeroMuted: '#a5b4fc',
  success: '#4ade80',
  successSoft: 'rgba(74,222,128,0.14)',
  danger: '#f87171',
  dangerSoft: 'rgba(248,113,113,0.14)',
  warning: '#fbbf24',
  warningSoft: 'rgba(251,191,36,0.14)',
  info: '#60a5fa',
  infoSoft: 'rgba(96,165,250,0.14)',
  neutral: '#94a3b8',
  neutralSoft: 'rgba(148,163,184,0.14)',
  primaryText: '#a5b4fc',
  primaryBorder: 'rgba(129,140,248,0.35)',
  successText: '#4ade80',
  successBorder: 'rgba(74,222,128,0.35)',
  dangerText: '#f87171',
  dangerBorder: 'rgba(248,113,113,0.35)',
  warningText: '#fbbf24',
  warningBorder: 'rgba(251,191,36,0.35)',
  infoText: '#60a5fa',
  shadowCard: {},
};

export const themes: Record<ColorScheme, ThemeTokens> = { light: lightTheme, dark: darkTheme };

/** The scheme actually shown: the user's explicit choice, else the phone's (light if unknown). */
export function resolveScheme(mode: ThemeMode, system: ColorScheme | null | undefined): ColorScheme {
  if (mode === 'light' || mode === 'dark') return mode;
  return system === 'dark' ? 'dark' : 'light';
}
