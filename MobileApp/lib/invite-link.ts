/**
 * Pull the invite token out of whatever the user pasted: the emailed web link
 * (https://host/invite/<token>), the app link (invoicepro://invite/<token>) or the bare token.
 */
export function parseInviteToken(input: string): string | null {
  const s = input.trim();
  if (!s) return null;
  const m = s.match(/invite\/([A-Za-z0-9_-]{8,})/);
  if (m) return m[1];
  return /^[A-Za-z0-9_-]{16,}$/.test(s) ? s : null;
}
