import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { useCan } from '@/hooks/use-access';
import { dismissOnboarding, Onboarding, OnboardingStep, OnboardingStepKey } from '@/services/onboarding';

export const ONBOARDING_KEY = ['onboarding'];

const ROUTE: Partial<Record<OnboardingStepKey, string>> = {
  customer: '/party/customer/new',
  invoice: '/invoice/new',
  share: '/invoices',
};

/**
 * "Get set up" card for brand-new accounts: the next undone step is highlighted and tappable, finished steps tick
 * themselves (the server derives them from real data), and the whole card disappears once everything is done.
 */
export function FirstRunChecklist({ data }: { data: Onboarding | undefined }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const qc = useQueryClient();
  const canCustomer = useCan('customer.manage');
  const canInvoice = useCan('invoice.create');
  const dismiss = useMutation({
    mutationFn: dismissOnboarding,
    onSuccess: (next) => qc.setQueryData(ONBOARDING_KEY, next),
  });

  if (!data?.visible) return null;
  const allowed = (k: OnboardingStepKey) => (k === 'customer' ? canCustomer : k === 'invoice' ? canInvoice : true);
  const steps = data.steps.filter((s) => s.done || allowed(s.key));
  const doneCount = steps.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done);

  const Row = ({ step }: { step: OnboardingStep }) => {
    const route = ROUTE[step.key];
    const isNext = next?.key === step.key;
    return (
      <TouchableOpacity
        style={styles.row} disabled={step.done || !route} onPress={() => route && router.push(route as never)}
        accessibilityRole="button" accessibilityLabel={step.title} accessibilityState={{ checked: step.done }}>
        <View style={[styles.dot, step.done && styles.dotDone]}>
          {step.done && <Ionicons name="checkmark" size={12} color={theme.success} />}
        </View>
        <Text style={[styles.rowText, step.done && styles.rowDone, isNext && styles.rowNext]}>{step.title}</Text>
        {isNext && <Ionicons name="arrow-forward" size={16} color={theme.primary} />}
      </TouchableOpacity>
    );
  };

  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Text style={styles.title}>Get set up</Text>
        <Text style={styles.count}>{doneCount} of {steps.length}</Text>
        <TouchableOpacity onPress={() => dismiss.mutate()} hitSlop={12} accessibilityLabel="Hide checklist">
          <Ionicons name="close" size={18} color={theme.textMuted} />
        </TouchableOpacity>
      </View>
      <View style={styles.bar}><View style={[styles.fill, { width: `${(doneCount / Math.max(steps.length, 1)) * 100}%` }]} /></View>
      {steps.map((s) => <Row key={s.key} step={s} />)}
    </View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  card: { backgroundColor: t.surface, borderRadius: 16, borderWidth: 1, borderColor: t.border, padding: 16, marginBottom: 16 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { flex: 1, fontSize: 17, fontWeight: '800', color: t.text },
  count: { fontSize: 13, color: t.textMuted, fontWeight: '600' },
  bar: { height: 6, borderRadius: 3, backgroundColor: t.background, overflow: 'hidden', marginVertical: 12 },
  fill: { height: '100%', backgroundColor: t.primary },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 11, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border },
  dot: { width: 20, height: 20, borderRadius: 10, borderWidth: 1.5, borderColor: t.border, alignItems: 'center', justifyContent: 'center' },
  dotDone: { backgroundColor: t.successSoft, borderColor: t.successBorder },
  rowText: { flex: 1, fontSize: 15, color: t.text },
  rowDone: { color: t.textFaint, textDecorationLine: 'line-through' },
  rowNext: { fontWeight: '700' },
});
