/**
 * Maps incoming links onto app routes. The web app lives under /app on the site, so an
 * emailed invite link arrives as https://invoice.orvine.in/app/invite/<token>; the app's
 * route is just /invite/<token>. (The invoicepro:// scheme already matches as-is.)
 */
export function redirectSystemPath({ path }: { path: string; initial: boolean }) {
  const m = path.match(/(?:^|\/)app\/(invite\/[A-Za-z0-9_-]+)/);
  if (m) return `/${m[1]}`;
  // Links that only launch the app are not routes: the development client opens it with invoicepro:/// or
  // invoicepro://expo-development-client/?url=<metro>, or hands over the bare Metro address. Returning null
  // lets the app start where it normally does (login when signed out, home when signed in) — sending these
  // to "/" instead lands on a screen that only exists once signed in, i.e. "Unmatched Route".
  if (/^invoicepro:\/*$/.test(path) || path.includes('expo-development-client') || /^https?:\/\/[^/]*:\d+\/?$/.test(path)) {
    return null;
  }
  return path;
}
