import { darkTheme, lightTheme, resolveScheme } from '@/constants/theme';

describe('resolveScheme', () => {
  it('honours an explicit choice over the phone setting', () => {
    expect(resolveScheme('dark', 'light')).toBe('dark');
    expect(resolveScheme('light', 'dark')).toBe('light');
  });

  it('follows the phone in system mode, defaulting to light when unknown', () => {
    expect(resolveScheme('system', 'dark')).toBe('dark');
    expect(resolveScheme('system', 'light')).toBe('light');
    expect(resolveScheme('system', null)).toBe('light');
    expect(resolveScheme('system', undefined)).toBe('light');
  });
});

describe('theme tokens', () => {
  it('defines the same tokens in light and dark', () => {
    expect(Object.keys(darkTheme).sort()).toEqual(Object.keys(lightTheme).sort());
  });

  it('keeps dark elevation ordered by lightness', () => {
    const lum = (hex: string) => parseInt(hex.slice(1), 16);
    expect(lum(darkTheme.background)).toBeLessThan(lum(darkTheme.surface));
    expect(lum(darkTheme.surface)).toBeLessThan(lum(darkTheme.surfaceRaised));
  });

  it('has no card shadow in dark mode', () => {
    expect(darkTheme.shadowCard).toEqual({});
  });
});
