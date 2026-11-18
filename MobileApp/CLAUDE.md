# MobileApp

## UI and theming

Before creating or editing any screen or component, read [DARK_THEME.md](DARK_THEME.md). Every UI must work in both light and dark mode:

- Use theme tokens from `useTheme()` / `useThemedStyles()`; never hard-code hex colors (the old `Palette` is gone).
- Invoice previews, PDFs, and template output always stay white.
- Run the QA checklist in DARK_THEME.md section 9 before finishing UI work.
