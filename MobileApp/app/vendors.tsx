import { Stack } from 'expo-router';
import { PartyList } from '@/components/party-list';

export default function VendorsScreen() {
  return (
    <>
      <Stack.Screen options={{ title: 'Vendors' }} />
      <PartyList kind="vendor" topInset={false} />
    </>
  );
}
