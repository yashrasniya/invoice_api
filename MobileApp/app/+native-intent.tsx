/**
 * Maps incoming links onto app routes. The web app lives under /app on the site, so an
 * emailed invite link arrives as https://invoice.orvine.in/app/invite/<token>; the app's
 * route is just /invite/<token>. (The invoicepro:// scheme already matches as-is.)
 */
export function redirectSystemPath({ path }: { path: string; initial: boolean }) {
  const m = path.match(/(?:^|\/)app\/(invite\/[A-Za-z0-9_-]+)/);
  return m ? `/${m[1]}` : path;
}
