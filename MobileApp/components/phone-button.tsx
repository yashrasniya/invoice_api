import React from 'react';
import { router } from 'expo-router';
import { Button } from '@/components/ui/button';
import { phoneSignInAvailable } from '@/lib/phone-auth';

export { phoneSignInAvailable };

/** "Continue with phone" — opens the OTP screen (hidden in builds without Firebase). */
export function PhoneButton({ disabled, style, title = 'Continue with phone' }: { disabled?: boolean; style?: object; title?: string }) {
  if (!phoneSignInAvailable) return null;
  return <Button title={title} icon="call-outline" variant="outline" onPress={() => router.push('/phone-login')} disabled={disabled} style={style} />;
}
