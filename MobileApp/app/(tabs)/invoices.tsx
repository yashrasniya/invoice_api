import React from 'react';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { InvoiceList } from '@/components/invoice-list';

export default function InvoicesScreen() {
  const insets = useSafeAreaInsets();
  return <InvoiceList type="sales" title="Invoices" topInset={insets.top} />;
}
