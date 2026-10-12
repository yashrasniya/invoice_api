import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { Platform } from 'react-native';
import api from '@/services/api';

export type PushResult =
  | { ok: true; token: string }
  | { ok: false; reason: 'simulator' | 'denied' | 'no_project' | 'error'; message: string };

/** Show alerts while the app is open too, instead of silently dropping them. */
export function configureNotifications() {
  if (Platform.OS === 'web') return;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false,
    }),
  });
}

/** Route a tapped notification to the screen it is about. */
export function routeFromNotification(data: Record<string, unknown> | undefined) {
  if (data?.type === 'ocr') router.push('/purchases/scan');
}

const projectId = () =>
  (Constants.expoConfig?.extra as any)?.eas?.projectId ?? (Constants as any).easConfig?.projectId ?? null;

/**
 * Ask permission (only when the user turned the setting on), get this phone's Expo push token
 * and tell the backend. Never throws: the caller shows `message` if `ok` is false.
 */
export async function registerForPush(): Promise<PushResult> {
  try {
    if (Platform.OS === 'web') return { ok: false, reason: 'simulator', message: 'Push notifications are only available in the phone app.' };
    if (!Device.isDevice) return { ok: false, reason: 'simulator', message: 'Push notifications need a real phone, not a simulator.' };

    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Default', importance: Notifications.AndroidImportance.DEFAULT,
      });
    }

    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return { ok: false, reason: 'denied', message: 'Notifications are turned off for this app in your phone settings.' };

    const id = projectId();
    if (!id) return { ok: false, reason: 'no_project', message: 'This build is not linked to an EAS project yet, so it cannot receive push notifications.' };

    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId: id });
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
  if (Platform.OS === 'web') return;
  try {
    const id = projectId();
    if (!id || !Device.isDevice) return;
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId: id });
    await api.delete('devices/', { data: { token } });
  } catch {
    /* best effort: a stale row is pruned by the server when Expo reports the device gone */
  }
}
