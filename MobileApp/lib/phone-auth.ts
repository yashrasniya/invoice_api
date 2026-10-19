type AuthModule = typeof import('@react-native-firebase/auth');
type Confirmation = Awaited<ReturnType<AuthModule['signInWithPhoneNumber']>>;

let loaded: AuthModule | null | undefined;

/**
 * Like the Google module, Firebase's native part is not in Expo Go, and importing it there throws. Load it on
 * demand; where it can't load, phone sign-in is simply unavailable (the button is hidden).
 */
function firebaseAuth(): AuthModule | null {
  if (loaded !== undefined) return loaded;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    loaded = require('@react-native-firebase/auth') as AuthModule;
    loaded.getAuth(); // throws when this build has no Firebase config (google-services.json / plist)
  } catch {
    loaded = null;
  }
  return loaded;
}

export const phoneSignInAvailable = firebaseAuth() !== null;

/** The 10 digit Indian number (or a full +country number) as Firebase wants it: E.164. */
export function toE164(input: string): string | null {
  const t = input.trim();
  const digits = t.replace(/\D/g, '');
  if (t.startsWith('+')) return digits.length >= 8 && digits.length <= 15 ? `+${digits}` : null;
  const national = digits.length === 12 && digits.startsWith('91') ? digits.slice(2) : digits.replace(/^0+(?=\d{10}$)/, '');
  return /^[6-9]\d{9}$/.test(national) ? `+91${national}` : null;
}

export type PhoneChallenge = { confirm: (code: string) => Promise<string> };

/** Sends the SMS code. `confirm(code)` resolves to the Firebase ID token the backend exchanges for a session. */
export async function startPhoneSignIn(e164: string): Promise<PhoneChallenge> {
  const F = firebaseAuth();
  if (!F) throw new Error('Phone sign-in is not set up in this build.');
  const auth = F.getAuth();
  let confirmation: Confirmation;
  try {
    confirmation = await F.signInWithPhoneNumber(auth, e164);
  } catch (e) {
    throw new Error(readable(e, 'Could not send the code. Check the number and try again.'));
  }
  return {
    confirm: async (code: string) => {
      try {
        const cred = await confirmation.confirm(code.trim());
        if (!cred) throw new Error('No result');
        const idToken = await F.getIdToken(cred.user);
        await F.signOut(auth).catch(() => {}); // Firebase's own session isn't needed: our API issues the real one
        return idToken;
      } catch (e) {
        throw new Error(readable(e, 'That code did not work. Try again.'));
      }
    },
  };
}

function readable(e: unknown, fallback: string): string {
  const code = (e as { code?: string })?.code ?? '';
  console.warn('[phone-auth]', code, (e as Error)?.message);
  if (code.includes('invalid-phone-number')) return 'That phone number is not valid.';
  if (code.includes('too-many-requests')) return 'Too many attempts. Please wait a while and try again.';
  if (code.includes('invalid-verification-code')) return 'That code is incorrect.';
  if (code.includes('code-expired') || code.includes('session-expired')) return 'That code has expired. Request a new one.';
  if (code.includes('quota-exceeded')) return 'SMS limit reached. Please try again later.';
  // surface Firebase's own code (e.g. auth/internal-error, auth/missing-client-identifier) so setup problems are diagnosable
  return code ? `${fallback} (${code})` : fallback;
}
