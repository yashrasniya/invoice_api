import React from 'react';
import { Text } from 'react-native';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Centered } from '@/components/ui/bits';
import { InvoiceForm } from '@/components/invoice-form';
import { errorMessage } from '@/services/api';
import { getInvoice } from '@/services/invoices';

export default function EditInvoiceScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useQuery({ queryKey: ['invoice', Number(id)], queryFn: () => getInvoice(Number(id)) });

  return (
    <>
      <Stack.Screen options={{ title: 'Edit invoice' }} />
      {q.isLoading ? <Centered /> : q.data ? <InvoiceForm invoice={q.data} /> : <Centered><Text>{errorMessage(q.error)}</Text></Centered>}
    </>
  );
}
