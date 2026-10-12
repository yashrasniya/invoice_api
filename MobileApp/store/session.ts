import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { Alert } from 'react-native';
import { setApiHandlers } from '@/services/api';
import { clearToken, getToken, setToken } from '@/services/token-storage';
import { Access, User, fetchAccess, fetchProfile, logoutRequest } from '@/services/auth';
import { unregisterPush } from '@/lib/push';

/** `error`: signed in, but the account could not be loaded and nothing is cached — show a retry screen. */
type Status = 'loading' | 'signedOut' | 'signedIn' | 'error';

const SNAPSHOT_KEY = 'session-snapshot-v1';

/**
 * Last known user + permissions, so the app can open offline. It is only a hint for the UI: the server
 * still enforces every permission on every request, and the snapshot is replaced as soon as a load succeeds.
 */
const saveSnapshot = (user: User, access: Access) =>
  AsyncStorage.setItem(SNAPSHOT_KEY, JSON.stringify({ user, access })).catch(() => {});
const clearSnapshot = () => AsyncStorage.removeItem(SNAPSHOT_KEY).catch(() => {});
async function readSnapshot(): Promise<{ user: User; access: Access } | null> {
  try {
    const raw = await AsyncStorage.getItem(SNAPSHOT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

type SessionState = {
  status: Status;
  user: User | null;
  access: Access | null;
  /** Restore a saved session on app start. */
  bootstrap: () => Promise<void>;
  /** Persist a fresh token (from login / invite accept) and load the user context. */
  signIn: (token: string, user?: User) => Promise<void>;
  signOut: () => Promise<void>;
  setUser: (user: User) => void;
  refreshAccess: () => Promise<void>;
};

export const useSession = create<SessionState>((set, get) => ({
  status: 'loading',
  user: null,
  access: null,

  bootstrap: async () => {
    const token = await getToken();
    if (!token) return set({ status: 'signedOut' });
    try {
      const [user, access] = await Promise.all([fetchProfile(), fetchAccess()]);
      saveSnapshot(user, access);
      set({ user, access, status: 'signedIn' });
    } catch (e: any) {
      // Only an auth failure ends the session; being offline or a server hiccup must not log the user out.
      if (e?.response?.status === 401) {
        await clearToken();
        await clearSnapshot();
        return set({ status: 'signedOut' });
      }
      const snap = await readSnapshot();
      if (snap) set({ user: snap.user, access: snap.access, status: 'signedIn' });
      else set({ status: 'error' });
    }
  },

  signIn: async (token, user) => {
    await setToken(token);
    const [profile, access] = await Promise.all([user ? Promise.resolve(user) : fetchProfile(), fetchAccess()]);
    saveSnapshot(profile, access);
    set({ user: profile, access, status: 'signedIn' });
  },

  signOut: async () => {
    // while the token is still valid: stop this phone getting the user's notifications
    await unregisterPush();
    try { await logoutRequest(); } catch { /* token may already be invalid */ }
    await clearToken();
    await clearSnapshot();
    set({ user: null, access: null, status: 'signedOut' });
  },

  setUser: (user) => set({ user }),

  refreshAccess: async () => {
    const access = await fetchAccess();
    set({ access });
    const user = get().user;
    if (user) saveSnapshot(user, access);
  },
}));

let upgradeAlertOpen = false;
setApiHandlers({
  onUnauthorized: () => {
    if (useSession.getState().status === 'signedIn') {
      clearToken().then(() => { clearSnapshot(); useSession.setState({ user: null, access: null, status: 'signedOut' }); });
    }
  },
  onUpgradeRequired: (message) => {
    if (upgradeAlertOpen) return;
    upgradeAlertOpen = true;
    Alert.alert('Upgrade required', message, [{ text: 'OK', onPress: () => { upgradeAlertOpen = false; } }], {
      onDismiss: () => { upgradeAlertOpen = false; },
    });
  },
});
