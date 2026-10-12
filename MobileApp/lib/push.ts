import Constants from 'expo-constants';
import * as Device from 'expo-device';
import { router } from 'expo-router';
import { Platform } from 'react-native';
import api from '@/services/api';

type NotificationsModule = typeof import('expo-notifications');

let cached: NotificationsModule | null | undefined;

/**
 * expo-notifications is loaded on demand, never at app start. Its native part is missing from Expo Go
 * (Android) and from web, and merely importing it there throws — which used to crash the whole app on
 * launch. When it can't load, push features switch off and everything else works.
 */
function notifications(): NotificationsModule | null {
  if (cached !== undefined) return cached;
  if (Platform.OS === 'web') return (cached = null);
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    cached = require('expo-notifications') as NotificationsModule;
  } catch {
    cached = null;
  }
  return cached;
}

export type PushResult =
  | { ok: true; token: string }
  | { ok: false; reason: 'simulator' | 'denied' | 'no_project' | 'unavailable' | 'error'; message: string };

const UNAVAILABLE =
  'Push notifications are not available in this version of the app (they need the installed app, not Expo Go).';

/** Show alerts while the app is open too, instead of silently dropping them. */
export function configureNotifications() {
  const N = notifications();
  if (!N) return;
  N.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false,
    }),
  });
}

/** Route a tapped notification to the screen it is about. */
function routeFromNotification(data: Record<string, unknown> | undefined) {
  if (data?.type === 'ocr') router.push('/purchases/scan');
}

/**
 * Open the right screen when the user taps a notification (including the one that launched the app).
 * Returns a cleanup function; does nothing where notifications are unavailable.
 */
export function listenForNotificationTaps(): () => void {
  const N = notifications();
  if (!N) return () => {};
  N.getLastNotificationResponseAsync()
    .then((r) => r && routeFromNotification(r.notification.request.content.data))
    .catch(() => {});
  const sub = N.addNotificationResponseReceivedListener((r) => routeFromNotification(r.notification.request.content.data));
  return () => sub.remove();
}

const projectId = () =>
  (Constants.expoConfig?.extra as any)?.eas?.projectId ?? (Constants as any).easConfig?.projectId ?? null;

/**
 * Ask permission (only when the user turned the setting on), get this phone's Expo push token
 * and tell the backend. Never throws: the caller shows `message` if `ok` is false.
 */
export async function registerForPush(): Promise<PushResult> {
  try {
    const N = notifications();
    if (!N) return { ok: false, reason: 'unavailable', message: UNAVAILABLE };
    if (!Device.isDevice) return { ok: false, reason: 'simulator', message: 'Push notifications need a real phone, not a simulator.' };

    if (Platform.OS === 'android') {
      await N.setNotificationChannelAsync('default', { name: 'Default', importance: N.AndroidImportance.DEFAULT });
    }

    let { status } = await N.getPermissionsAsync();
    if (status !== 'granted') status = (await N.requestPermissionsAsync()).status;
    if (status !== 'granted') return { ok: false, reason: 'denied', message: 'Notifications are turned off for this app in your phone settings.' };

    const id = projectId();
    if (!id) return { ok: false, reason: 'no_project', message: 'This build is not linked to an EAS project yet, so it cannot receive push notifications.' };

    const { data: token } = await N.getExpoPushTokenAsync({ projectId: id });
    await api.post('devices/', { token, platform: Platform.OS });
    return { ok: true, token };
  } catch (e) {
    const msg = e instanceof Error ? e.message : '';
    // Android without google-services.json: Firebase was never initialised in this build
    if (/firebase/i.test(msg) && /initiali[sz]ed/i.test(msg)) {
      return {
        ok: false, reason: 'error',
        message: 'Push notifications are not set up for this version of the app yet. Everything else works normally.',
      };
    }
    return { ok: false, reason: 'error', message: msg || 'Could not enable notifications.' };
  }
}

/** Stop this phone receiving the signed-in user's notifications (call before the token is discarded). */
export async function unregisterPush() {
  try {
    const N = notifications();
    const id = projectId();
    if (!N || !id || !Device.isDevice) return;
    const { data: token } = await N.getExpoPushTokenAsync({ projectId: id });
    await api.delete('devices/', { data: { token } });
  } catch {
    /* best effort: a stale row is pruned by the server when Expo reports the device gone */
  }
}
