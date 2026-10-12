type GoogleModule = typeof import('@react-native-google-signin/google-signin');

let loaded: GoogleModule | null | undefined;

/**
 * The library's native part is not in Expo Go, and merely importing it there throws — which crashed the whole
 * app before the login screen could draw. Load it on demand; where it can't load, Google sign-in is simply
 * unavailable (the button is hidden) and email/password login keeps working.
 */
function google(): GoogleModule | null {
  if (loaded !== undefined) return loaded;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    loaded = require('@react-native-google-signin/google-signin') as GoogleModule;
  } catch {
    loaded = null;
  }
  return loaded;
}

/** The *web* OAuth client ID: Google puts it in the ID token's audience, and the backend verifies it. */
const WEB_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? '';

export const googleSignInConfigured = WEB_CLIENT_ID.length > 0 && google() !== null;

let configured = false;

/** Returns the ID token, or null if the user closed the sheet. Throws a readable Error otherwise. */
export async function getGoogleIdToken(): Promise<string | null> {
  const G = google();
  if (!googleSignInConfigured || !G) throw new Error('Google sign-in is not set up in this build.');
  const { GoogleSignin, isErrorWithCode, isSuccessResponse, statusCodes } = G;
  if (!configured) {
    GoogleSignin.configure({ webClientId: WEB_CLIENT_ID });
    configured = true;
  }
  try {
    await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    // forget the previous account so the user can choose which one to use
    await GoogleSignin.signOut().catch(() => {});
    const res = await GoogleSignin.signIn();
    if (!isSuccessResponse(res)) return null;
    if (!res.data.idToken) throw new Error('Google did not return an ID token.');
    return res.data.idToken;
  } catch (e) {
    if (isErrorWithCode(e)) {
      if (e.code === statusCodes.SIGN_IN_CANCELLED) return null;
      if (e.code === statusCodes.IN_PROGRESS) return null;
      if (e.code === statusCodes.PLAY_SERVICES_NOT_AVAILABLE) throw new Error('Google Play services are not available on this device.');
    }
    throw new Error('Google sign-in failed. Check the OAuth client setup (package name and SHA-1) and try again.');
  }
}
