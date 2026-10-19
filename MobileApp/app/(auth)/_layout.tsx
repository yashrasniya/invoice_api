import { Stack } from 'expo-router';

export const unstable_settings = { initialRouteName: 'login' };

export default function AuthLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="login" />
      <Stack.Screen name="signup" />
      <Stack.Screen name="phone-login" />
    </Stack>
  );
}
