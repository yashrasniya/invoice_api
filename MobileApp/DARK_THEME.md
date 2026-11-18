# Dark Theme Design Spec

> **Audience:** developers and LLMs building or changing any screen/component in `MobileApp/`.
> **Rule:** read this file before writing UI. Every new page must look correct in **both** light and dark mode.
> **Status:** implemented. Tokens live in `constants/theme.ts` (`lightTheme`, `darkTheme`), the `useTheme()` / `useThemedStyles()` hooks in `hooks/use-theme.ts`, the saved choice in `usePrefs().themeMode`, and the System / Light / Dark selector in Profile (`components/theme-mode-picker.tsx`). All existing screens use the tokens; the old light-only `Palette` object has been removed.

---

## 1. Design intent

- **Calm, professional, finance-grade.** This is an invoicing/GST app used for long sessions, often in low light (shops, evenings). Dark mode must reduce glare without hurting readability of numbers.
- **Brand stays recognisable:** indigo primary (`#4f46e5` light, softened to `#818cf8` in dark) on a slate base.
- **Not pure black.** Backgrounds are deep navy-slate. True black (`#000`) is only an optional "OLED" variant, not the default.
- **Depth comes from lightness, not shadows.** Higher layers are lighter than lower ones.
- **Numbers first.** Amounts, totals and due balances are the most important content; they get the highest contrast and tabular figures.

Reference conventions: Material 3 dark theme, Apple HIG dark mode, and common invoicing apps (Stripe Dashboard, Zoho Invoice, Wave, Vyapar, Khatabook).

---

## 2. Theme behaviour

| Setting | Behaviour |
|---|---|
| Modes | `system` (default), `light`, `dark` |
| Persistence | User choice stored in AsyncStorage; `system` follows `useColorScheme()` |
| Selector | Profile screen: System / Light / Dark |
| `app.json` | `"userInterfaceStyle": "automatic"`; splash has a dark variant (`#0b1120`) |
| Switching | Instant, no app restart, no flash of the wrong theme on cold start |

---

## 3. Color tokens

**Never hard-code hex values in screens or components.** Always read from the theme: `const theme = useTheme();` then `theme.surface`, `theme.text`, etc. (Use `theme`, not `t`, in components: `t` is already used as a loop variable in many screens.)

### 3.1 Surfaces (elevation by lightness)

| Token | Light | Dark | Used for |
|---|---|---|---|
| `background` | `#f8fafc` | `#0b1120` | Screen background |
| `surface` | `#ffffff` | `#131c2e` | Cards, list rows, sheets |
| `surfaceRaised` | `#ffffff` | `#1b2740` | Modals, dropdowns, inputs, popovers |
| `surfaceMuted` | `#f1f5f9` | `#0f1729` | Table headers, disabled fields, wells |
| `border` | `#e2e8f0` | `#26324a` | Card borders, dividers, input outlines |
| `borderStrong` | `#cbd5e1` | `#33425f` | Focused/hovered outlines, table grid |
| `overlay` | `rgba(15,23,42,0.45)` | `rgba(0,0,0,0.65)` | Modal scrim |

Elevation ladder in dark: `background` < `surface` < `surfaceRaised`. A card on a modal must be lighter than the modal.

### 3.2 Text

| Token | Light | Dark | Used for |
|---|---|---|---|
| `text` | `#0f172a` | `#e5e9f2` | Primary text, amounts, titles |
| `textMuted` | `#64748b` | `#94a3b8` | Secondary text, labels, captions |
| `textFaint` | `#94a3b8` | `#64748b` | Placeholders, disabled text, hints |
| `textInverse` | `#ffffff` | `#0b1120` | Text on filled primary/success buttons |
| `label` | `#334155` | `#cbd5e1` | Form field labels |

Never use pure `#fff` for body text in dark mode (too harsh). Minimum contrast: **4.5:1** for body text, **3:1** for large text (>= 18 px or >= 14 px bold) and UI icons.

### 3.3 Brand and actions

| Token | Light | Dark | Used for |
|---|---|---|---|
| `primary` | `#4f46e5` | `#818cf8` | Primary buttons, active tab, links, focus ring |
| `primaryPressed` | `#4338ca` | `#6366f1` | Pressed state |
| `primarySoft` | `#eef2ff` | `rgba(129,140,248,0.16)` | Selected row, tinted chip/background |
| `onPrimary` | `#ffffff` | `#0b1120` | Label on a filled primary button |
| `accent` | `#7c3aed` | `#a78bfa` | Secondary brand accent, gradients (use sparingly) |

Saturated indigo (`#4f46e5`) vibrates on dark backgrounds; always use the lighter dark-mode value.

### 3.4 Status colors

| Status | Token | Light | Dark | Soft background (dark) |
|---|---|---|---|---|
| Success / Paid | `success` | `#16a34a` | `#4ade80` | `rgba(74,222,128,0.14)` |
| Danger / Overdue | `danger` | `#dc2626` | `#f87171` | `rgba(248,113,113,0.14)` |
| Warning / Due soon | `warning` | `#d97706` | `#fbbf24` | `rgba(251,191,36,0.14)` |
| Info / Draft | `info` | `#2563eb` | `#60a5fa` | `rgba(96,165,250,0.14)` |
| Neutral / Cancelled | `neutral` | `#64748b` | `#94a3b8` | `rgba(148,163,184,0.14)` |

Each status also has `*Soft` (tinted background), `*Text` (readable text on that tint) and, for primary/success/danger/warning, `*Border` tokens, e.g. `successSoft` + `successText`. Use those instead of picking hexes. **Hero cards** (plan / upgrade banners) use `hero`, `onHero`, `onHeroMuted`: solid indigo in light, a deep indigo tint in dark.

**Chips and badges in dark mode:** tinted soft background + the bright status color as text. Do not use solid saturated fills; they glow and look heavy.

**Never rely on color alone** to convey status. Pair it with an icon or label text ("Paid", "Overdue").

---

## 4. Component rules

Existing shared UI lives in `components/ui/` (`button.tsx`, `field.tsx`, `bits.tsx`). Update those first; screens inherit the change.

### Cards and lists
- Fill `surface`, 1 px `border`, radius **16** (common) or 12. **No drop shadows in dark mode** (invisible and muddy). Light mode may keep a subtle shadow; gate it with `isDark ? undefined : shadow`.
- List rows separated by a 1 px `border` hairline, not by alternating fills.
- Selected row: `primarySoft` background.

### Buttons
- **Primary:** fill `primary`, label `onPrimary`, radius 12.
- **Secondary / outline:** transparent fill, 1 px `borderStrong`, label `text`.
- **Destructive:** soft `danger` background with `danger` label, or solid `danger` with `#0b1120` label in dark.
- **Disabled:** 40% opacity on the same fill; never change to an unrelated gray.
- Pressed state is always visible (darker/lighter shade or opacity 0.85).

### Inputs and forms
- Fill `surfaceRaised`, 1 px `border`, radius 12, text `text`, placeholder `textFaint`.
- Focus: 1.5 px `primary` border (no glow).
- Error: `danger` border plus `danger` helper text below.
- Label above the field in `label`, 12-13 px, medium weight.
- Keyboard appearance must follow the theme (`keyboardAppearance={isDark ? 'dark' : 'light'}`).

### Tables (invoice line items, reports)
- Header row `surfaceMuted`, body `surface`, grid lines `border`.
- Amount columns right-aligned with `fontVariant: ['tabular-nums']`.
- Totals row: `surfaceRaised`, bold, `text`.

### Navigation
- Tab bar: `surface` background, top border `border`; active tint `primary`, inactive `textMuted`.
- Header: `background` (not `surface`) so it blends with the screen; no bottom shadow.
- Status bar: `light-content` in dark, `dark-content` in light (use `expo-status-bar` `style="auto"`).

### Modals and bottom sheets
- Fill `surfaceRaised`, top radius 16-20, scrim `overlay`.
- Drag handle in `borderStrong`.

### Charts (`components/charts.tsx`, reports)
- Grid lines `border` at low opacity; axis labels `textMuted`.
- Series colors use the **dark-mode lightened** values: indigo `#818cf8`, green `#4ade80`, amber `#fbbf24`, rose `#f87171`, sky `#60a5fa`, violet `#a78bfa`.
- Tooltips use `surfaceRaised` with `border`.
- Must stay distinguishable without color (labels, patterns or direct value labels).

### Icons and images
- Icons use `text` / `textMuted` / `primary`, never hard-coded black or white.
- Logos and photos with transparent or white backgrounds: place on a `#ffffff` rounded tile in dark mode.
- Empty-state illustrations must work on `background` (avoid white-fill SVGs).

### Dividers, skeletons, loaders
- Skeleton: base `surfaceRaised`, shimmer `borderStrong`.
- Activity indicator color: `primary`.

---

## 5. Typography and numbers

Keep the existing scale; only color changes per theme.

| Role | Size | Weight |
|---|---|---|
| Screen title | 20-22 | 700 |
| Section title | 16-18 | 600 |
| Body | 14-16 | 400-500 |
| Caption / label | 12-13 | 500 |

- Amounts: `tabular-nums`, weight 600-700, color `text` (use `success` / `danger` only for explicit paid/overdue amounts).
- Dark mode text looks bolder than light on the same weight; prefer 400-500 for body and avoid 300.
- Spacing and radii are unchanged between themes: base padding 16, gaps 8/12, radii 12/16/999 (pills).

---

## 6. Invoice-specific rules

- **Invoice preview, PDF, print and WhatsApp share output are always white "paper".** In dark mode, show the preview inside a `#ffffff` card (radius 12) floating on the dark `background`. Never invert invoice content.
- **Template designer / WebView content** renders on a white canvas regardless of theme. Only the surrounding chrome (toolbars, panels) is themed.
- Generated HTML templates in `invoice_api/templates/` are **not** themed.
- Money in the invoice list: amount `text`, status as a tinted chip (section 3.4), due date `textMuted` (becomes `danger` when overdue).
- Pro / upsell banners: `primarySoft` background with `primary` accent text, never a bright full-bleed gradient in dark mode.

---

## 7. Implementation guide for new pages

1. In the component, call `const theme = useTheme();` for inline colors (icons, `ActivityIndicator`, `placeholderTextColor`, props that need a color string).
2. Put the styles in a module-level `makeStyles` and read them with `useThemedStyles`:
3. Use `ThemedView` / `ThemedText` and the `components/ui` primitives (`Button`, `Field`, `bits`) where they fit; they are already themed.
4. Always set an explicit background color on the screen root.
5. Anything that must stay constant in both themes (camera overlays, invoice paper) is the only place a literal color is allowed; add a comment saying why.
6. Test both modes (see checklist below) before calling the page done.

```tsx
const makeStyles = (t: Theme) => StyleSheet.create({
  card: { backgroundColor: t.surface, borderColor: t.border, borderWidth: 1, borderRadius: 16, padding: 16, ...t.shadowCard },
  title: { color: t.text, fontSize: 16, fontWeight: '600' },
  due: { color: t.textMuted, fontSize: 13 },
});

export function InvoiceCard() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.card}>
      <Ionicons name="document-text" size={18} color={theme.primary} />
      <Text style={styles.title}>Invoice #1042</Text>
      <Text style={styles.due}>Due 28 Oct</Text>
    </View>
  );
}
```

Do not define a theme-dependent color at module level (e.g. a `const TONES = { paid: theme.x }`); make it a function of the theme and call it inside the component.

---

## 8. Do and don't

| Do | Don't |
|---|---|
| Use theme tokens everywhere | Hard-code `#fff`, `#000`, `#0f172a`, or any hex in screens |
| Lighten surfaces to show elevation | Use shadows or heavy borders for depth in dark mode |
| Use lighter, desaturated brand and status colors | Reuse light-mode saturated colors on dark backgrounds |
| Use tinted chips for status | Use solid neon fills |
| Keep invoice previews white | Invert or darken invoice output |
| Style keyboard, status bar, pickers, and alerts | Leave native components in light style |
| Add icon/text alongside status color | Convey meaning by color only |

---

## 9. QA checklist (every new or changed screen)

- [ ] Renders correctly in light, dark, and when the OS theme changes while the screen is open
- [ ] No white flash on navigation or cold start in dark
- [ ] No hard-coded colors (`grep -nE "#[0-9a-fA-F]{3,8}"` in the changed files)
- [ ] Text contrast >= 4.5:1 (body) / 3:1 (large text, icons)
- [ ] Inputs, placeholder, focus, and error states visible
- [ ] Status bar, keyboard, date/time picker, and alert dialogs match the theme
- [ ] Loading, empty, error, and offline states themed (see `offline-banner.tsx`, `error-screen.tsx`)
- [ ] Charts and tables legible; amounts right-aligned with tabular figures
- [ ] Invoice preview/PDF output unchanged (still white)
- [ ] Tested on a small phone and with large font scaling

---

## 10. Notes

- Camera screens (`app/inventory/scan.tsx`) keep literal black/white overlays on purpose; a camera preview is dark in both themes.
- `google-button.tsx`: Google's sign-in button must follow Google's brand guidelines (light or dark variants only); don't recolor it.
- `components/parallax-scroll-view.tsx` and `hello-wave.tsx` are Expo template leftovers and are not themed; delete rather than theme if unused.
- Changing `userInterfaceStyle` is a native config change: rebuild the dev client / EAS build to pick it up.
