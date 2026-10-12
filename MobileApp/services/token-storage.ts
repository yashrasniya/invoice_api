import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const KEY = 'auth_access_token';

// SecureStore has no web implementation; localStorage is the best the browser offers.
export async function getToken(): Promise<string | null> {
  if (Platform.OS === 'web') return globalThis.localStorage?.getItem(KEY) ?? null;
  return SecureStore.getItemAsync(KEY);
}

export async function setToken(token: string): Promise<void> {
  if (Platform.OS === 'web') return globalThis.localStorage?.setItem(KEY, token);
  await SecureStore.setItemAsync(KEY, token);
}

export async function clearToken(): Promise<void> {
  if (Platform.OS === 'web') return globalThis.localStorage?.removeItem(KEY);
  await SecureStore.deleteItemAsync(KEY);
}
