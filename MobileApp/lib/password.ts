export type PasswordFeedback = { ok: boolean; message: string };

/** The handful of passwords that make up most "too common" rejections. The server's list is the real authority. */
const COMMON = new Set([
  'password', 'password1', 'password123', '12345678', '123456789', '1234567890', '11111111', 'qwertyui', 'qwerty123',
  'iloveyou', 'abc12345', 'abcd1234', 'admin123', 'welcome1', 'letmein1', 'india123', 'sachin10', '987654321',
]);

type Who = { email?: string; name?: string };

/**
 * Live guidance under the password box, mirroring what the server will check (length, common, numeric-only,
 * similar to your details) so nobody finds out only after pressing the button. Never blocks on its own.
 */
export function passwordFeedback(password: string, who: Who = {}): PasswordFeedback {
  if (password.length < 8) {
    const left = 8 - password.length;
    return { ok: false, message: `${left} more character${left === 1 ? '' : 's'} to go (8 minimum)` };
  }
  const lower = password.toLowerCase();
  if (COMMON.has(lower)) return { ok: false, message: 'That password is very common. Pick something less guessable.' };
  if (/^\d+$/.test(password)) return { ok: false, message: 'Numbers only is easy to guess. Add some letters.' };
  const parts = [who.email?.split('@')[0], ...(who.name ?? '').split(/\s+/)]
    .map((p) => (p ?? '').toLowerCase())
    .filter((p) => p.length >= 4);
  if (parts.some((p) => lower.includes(p))) return { ok: false, message: 'Avoid using your name or email in your password.' };
  return { ok: true, message: 'Looks good' };
}
