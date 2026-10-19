import React from 'react';
import { Alert } from 'react-native';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/services/api';
import { googleLogin } from '@/services/auth';
import { getGoogleIdToken, googleSignInConfigured } from '@/lib/google-signin';
import { useSession } from '@/store/session';

type Props = { loading: boolean; setLoading: (v: boolean) => void; style?: object; title?: string };

export { googleSignInConfigured };

/** "Continue with Google" — shared by login and signup (the backend creates the account on first sign-in). */
export function GoogleButton({ loading, setLoading, style, title = 'Continue with Google' }: Props) {
  if (!googleSignInConfigured) return null;

  const onPress = async () => {
    setLoading(true);
    try {
      const idToken = await getGoogleIdToken();
      if (!idToken) return;
      const { token, user } = await googleLogin(idToken);
      await useSession.getState().signIn(token, user);
    } catch (e) {
      Alert.alert('Google sign-in failed', errorMessage(e, 'Could not sign in with Google.'));
    } finally {
      setLoading(false);
    }
  };

  return <Button title={title} icon="logo-google" variant="outline" onPress={onPress} disabled={loading} style={style} />;
}
