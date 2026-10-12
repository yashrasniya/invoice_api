import { DefaultTheme, ThemeProvider } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { QueryClient } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState } from 'react-native';
import 'react-native-reanimated';

import { LockGate } from '@/components/lock-gate';
import { OfflineBanner } from '@/components/offline-banner';
import { AccountError } from '@/components/account-error';
import { ErrorScreen } from '@/components/error-screen';
import { configureNotifications, listenForNotificationTaps, registerForPush } from '@/lib/push';
import { usePrefs } from '@/store/prefs';
import { useSession } from '@/store/session';

/** Shown by expo-router if a screen throws while rendering, instead of a blank crash. */
export function ErrorBoundary({ error, retry }: { error: Error; retry: () => void }) {
  return <ErrorScreen error={error} retry={retry} />;
}

SplashScreen.preventAutoHideAsync();

const DAY = 24 * 60 * 60 * 1000;

const queryClient = new QueryClient({
  // gcTime must be at least the persister's maxAge or restored data is dropped immediately
  defaultOptions: { queries: { retry: 1, staleTime: 30_000, gcTime: DAY } },
});

const persister = createAsyncStoragePersister({ storage: AsyncStorage, key: 'query-cache-v1' });

/**
 * Only everyday read screens are kept for offline use. Reports, billing, team and other
 * admin data are fetched fresh each time rather than copied onto the device.
 */
const OFFLINE_KEYS = new Set(['dashboard', 'invoices', 'invoice', 'parties', 'party', 'inventory', 'inventory-product', 'inventory-categories', 'columns']);

configureNotifications();

export default function RootLayout() {
  const status = useSession((s) => s.status);
  const needsCompany = useSession((s) => s.user && !s.user.is_company_varified);

  useEffect(() => {
    useSession.getState().bootstrap();
  }, []);

  useEffect(() => {
    if (status !== 'loading') SplashScreen.hideAsync();
  }, [status]);

  // Drop everything account-specific when signed out so the next user never sees it.
  useEffect(() => {
    if (status === 'signedOut') {
      queryClient.clear();
      persister.removeClient();
    }
  }, [status]);

  // If the user opted in to notifications, keep this phone registered while signed in.
  const pushEnabled = usePrefs((s) => s.pushEnabled);
  useEffect(() => {
    if (status === 'signedIn' && pushEnabled) registerForPush();
  }, [status, pushEnabled]);

  // Pick up permission/plan changes (and recover after being offline) when the app comes back to the foreground.
  useEffect(() => {
    if (status !== 'signedIn') return;
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') useSession.getState().refreshAccess().catch(() => {});
    });
    return () => sub.remove();
  }, [status]);

  // Tapping a notification opens the screen it is about (a no-op where notifications aren't available).
  useEffect(() => {
    if (status !== 'signedIn') return;
    return listenForNotificationTaps();
  }, [status]);

  if (status === 'loading') return null;
  if (status === 'error') return <AccountError />;

  const signedIn = status === 'signedIn';

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister,
        maxAge: DAY,
        buster: '1',
        dehydrateOptions: {
          shouldDehydrateQuery: (q) => q.state.status === 'success' && OFFLINE_KEYS.has(String(q.queryKey[0])),
        },
      }}>
      <ThemeProvider value={DefaultTheme}>
        <LockGate>
        <OfflineBanner />
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Protected guard={!signedIn}>
            <Stack.Screen name="(auth)" />
            <Stack.Screen name="invite/[token]" />
          </Stack.Protected>
          <Stack.Protected guard={signedIn && !!needsCompany}>
            <Stack.Screen name="company-setup" />
          </Stack.Protected>
          <Stack.Protected guard={signedIn && !needsCompany}>
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="profile" options={{ headerShown: true, title: 'My Profile' }} />
            <Stack.Screen name="vendors" options={{ headerShown: true }} />
            <Stack.Screen name="drafts" options={{ headerShown: true }} />
            <Stack.Screen name="billing" options={{ headerShown: true }} />
            <Stack.Screen name="whatsapp" options={{ headerShown: true }} />
            <Stack.Screen name="team" options={{ headerShown: true }} />
            <Stack.Screen name="templates" options={{ headerShown: true }} />
            <Stack.Screen name="numbering" options={{ headerShown: true }} />
            <Stack.Screen name="reports/index" options={{ headerShown: true }} />
            <Stack.Screen name="reports/sales" options={{ headerShown: true }} />
            <Stack.Screen name="reports/cash-flow" options={{ headerShown: true }} />
            <Stack.Screen name="reports/gst" options={{ headerShown: true }} />
            <Stack.Screen name="reports/ledger/[kind]/[id]" options={{ headerShown: true }} />
            <Stack.Screen name="purchases/index" options={{ headerShown: true }} />
            <Stack.Screen name="purchases/scan" options={{ headerShown: true }} />
            <Stack.Screen name="inventory/index" options={{ headerShown: true }} />
            <Stack.Screen name="inventory/[id]" options={{ headerShown: true }} />
            <Stack.Screen name="inventory/scan" options={{ headerShown: true }} />
            <Stack.Screen name="inventory/categories" options={{ headerShown: true }} />
            <Stack.Screen name="invoice/new" options={{ headerShown: true }} />
            <Stack.Screen name="invoice/[id]" options={{ headerShown: true }} />
            <Stack.Screen name="invoice/edit/[id]" options={{ headerShown: true }} />
            <Stack.Screen name="party/[kind]/[id]" options={{ headerShown: true }} />
          </Stack.Protected>
        </Stack>
        </LockGate>
        <StatusBar style="dark" />
      </ThemeProvider>
    </PersistQueryClientProvider>
  );
}
