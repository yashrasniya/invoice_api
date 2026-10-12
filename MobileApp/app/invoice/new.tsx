import React from 'react';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Centered } from '@/components/ui/bits';
import { InvoiceForm } from '@/components/invoice-form';
import { getInvoice } from '@/services/invoices';

export default function NewInvoiceScreen() {
  const { copy, type } = useLocalSearchParams<{ copy?: string; type?: string }>();
  const kind = type === 'purchase' ? 'purchase' : 'sales';
  const source = useQuery({
    queryKey: ['invoice', Number(copy)],
    queryFn: () => getInvoice(Number(copy)),
    enabled: !!copy,
  });

  return (
    <>
      <Stack.Screen options={{ title: copy ? 'Duplicate invoice' : kind === 'purchase' ? 'New purchase bill' : 'New invoice' }} />
      {copy && source.isLoading ? <Centered /> : <InvoiceForm copyFrom={source.data} type={kind} />}
    </>
  );
}
