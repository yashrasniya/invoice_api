import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { ThemeMode } from '@/constants/theme';

type Prefs = {
  /** require Face ID / fingerprint / device passcode when the app opens or returns after a while */
  biometricLock: boolean;
  /** the user opted in to push notifications on this device */
  pushEnabled: boolean;
  /** light, dark, or follow the phone */
  themeMode: ThemeMode;
  setBiometricLock: (v: boolean) => void;
  setThemeMode: (m: ThemeMode) => void;
  setPushEnabled: (v: boolean) => void;
};

/** Device-local preferences. Deliberately holds no business data and nothing account-specific. */
export const usePrefs = create<Prefs>()(
  persist(
    (set) => ({
      biometricLock: false,
      pushEnabled: false,
      themeMode: 'system',
      setBiometricLock: (biometricLock) => set({ biometricLock }),
      setPushEnabled: (pushEnabled) => set({ pushEnabled }),
      setThemeMode: (themeMode) => set({ themeMode }),
    }),
    { name: 'prefs-v1', storage: createJSONStorage(() => AsyncStorage) },
  ),
);
