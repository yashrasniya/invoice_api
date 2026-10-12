import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import { useSession } from '@/store/session';
import type { Column, InvoiceInput, InvoiceType, NewLine } from '@/services/invoices';

export type Draft = {
  id: string;
  createdAt: number;
  /** username that wrote it; other accounts on this phone never see it */
  owner: string;
  type: InvoiceType;
  partyName: string;
  input: InvoiceInput;
  lines: NewLine[];
  /** the column set the lines were written against, so a later retry stays consistent */
  columns: Column[];
};

type DraftState = {
  drafts: Draft[];
  add: (d: Omit<Draft, 'id' | 'createdAt'>) => void;
  remove: (id: string) => void;
};

/**
 * Invoices the user finished while offline, kept on the device until they can be sent.
 * Persisted per device and tagged with their owner. They are not cleared on sign-out (an expired
 * session must not destroy unsent work); they simply stay hidden from any other account.
 */
export const useDrafts = create<DraftState>()(
  persist(
    (set) => ({
      drafts: [],
      add: (d) =>
        set((s) => ({ drafts: [...s.drafts, { ...d, id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, createdAt: Date.now() }] })),
      remove: (id) => set((s) => ({ drafts: s.drafts.filter((d) => d.id !== id) })),
    }),
    { name: 'drafts-v1', storage: createJSONStorage(() => AsyncStorage) },
  ),
);

/** The signed-in user's drafts only. */
export function useMyDrafts() {
  const owner = useSession((s) => s.user?.username);
  const drafts = useDrafts((s) => s.drafts);
  return drafts.filter((d) => d.owner === owner);
}
