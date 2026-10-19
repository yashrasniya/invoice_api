import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useQuery } from '@tanstack/react-query';
import { Section } from '@/components/report-ui';
import { Button } from '@/components/ui/button';
import { Centered, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { useIsFreePlan } from '@/hooks/use-plan';
import { money } from '@/lib/invoice-calc';
import { trialInfo } from '@/lib/trial';
import { useSession } from '@/store/session';
import { errorMessage, WEB_URL } from '@/services/api';
import { fetchBilling, fetchPayments, fetchPlans } from '@/services/billing';

const fmt = (d: string | null | undefined) => (d ? new Date(d).toLocaleDateString() : '—');
const label = (s: string | null | undefined) => (s ? s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : '—');
const limitText = (limits: Record<string, number>) =>
  Object.entries(limits).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ');

export default function BillingScreen() {
  const canView = useCan('subscription.view');
  const canManage = useCan('subscription.manage');
  const isFree = useIsFreePlan();
  const trial = trialInfo(useSession((s) => s.access?.subscription));
  const status = useQuery({ queryKey: ['billing'], queryFn: fetchBilling, enabled: canView });
  const plans = useQuery({ queryKey: ['billing-plans'], queryFn: fetchPlans, enabled: canView });
  const payments = useQuery({ queryKey: ['billing-payments'], queryFn: fetchPayments, enabled: canView });

  // Payments are handled on the web for now.
  const openWeb = () => WEB_URL && WebBrowser.openBrowserAsync(`${WEB_URL}/billing`);

  if (!canView) {
    return <><Stack.Screen options={{ title: 'Plan & billing' }} /><EmptyState icon="lock-closed-outline" title="No access" hint="You don't have permission to view billing." /></>;
  }
  if (status.isLoading) return <Centered />;
  if (status.error) return <><Stack.Screen options={{ title: 'Plan & billing' }} /><EmptyState icon="alert-circle-outline" title="Couldn't load billing" hint={errorMessage(status.error)} /></>;

  const ent = status.data?.entitlement;
  const sub = status.data?.billing_subscription;
  const change = status.data?.scheduled_change;

  return (
    <>
      <Stack.Screen options={{ title: 'Plan & billing' }} />
      <ScrollView style={styles.screen} contentContainerStyle={{ padding: 16 }}
        refreshControl={<RefreshControl refreshing={status.isRefetching} onRefresh={() => { status.refetch(); plans.refetch(); payments.refetch(); }} />}>
        <View style={styles.current}>
          <Text style={styles.currentLabel}>Current plan</Text>
          <Text style={styles.currentName}>{ent?.plan_name ?? 'No active plan'}</Text>
          {!!ent && (
            <Text style={styles.currentMeta}>
              {label(ent.status)}{ent.end_date ? ` · ${ent.auto_renew ? 'renews' : 'ends'} ${fmt(ent.end_date)}` : ''}
            </Text>
          )}
          {sub?.cancel_at_cycle_end && <Text style={styles.warn}>Cancels at the end of this billing period.</Text>}
          {!!change && <Text style={styles.currentMeta}>Switching to {change.to_plan_name} on {fmt(change.effective_date)}.</Text>}
          {ent && !ent.is_working && <Text style={styles.warn}>This subscription is not active — some features are unavailable.</Text>}
        </View>

        <Button title={isFree || trial ? 'Upgrade your plan' : 'Change or manage plan on the web'} onPress={openWeb} style={{ marginBottom: 16 }} />
        {!canManage && <Text style={styles.note}>Only admins with billing access can change the plan.</Text>}

        <Section title="Available plans">
          {(plans.data ?? []).map((p) => (
            <View key={p.id} style={[styles.plan, p.is_current && styles.planCurrent]}>
              <View style={styles.rowBetween}>
                <Text style={styles.planName}>{p.name}{p.is_current ? '  ✓' : ''}</Text>
                <Text style={styles.planPrice}>{Number(p.monthly_price) ? `${money(p.monthly_price).replace('.00', '')}/mo` : 'Free'}</Text>
              </View>
              {!!Number(p.yearly_price) && <Text style={styles.planMeta}>{money(p.yearly_price).replace('.00', '')}/year</Text>}
              {p.features.map((f) => (
                <Text key={f.code} style={styles.feature}>• {f.name}{Object.keys(f.limits ?? {}).length ? ` — ${limitText(f.limits)}` : ''}</Text>
              ))}
            </View>
          ))}
        </Section>

        <Section title="Payment history">
          {(payments.data ?? []).length === 0 && <Text style={styles.planMeta}>No payments yet.</Text>}
          {(payments.data ?? []).slice(0, 15).map((p) => (
            <View key={p.id} style={styles.pay}>
              <View style={{ flex: 1 }}>
                <Text style={styles.payTitle}>{p.description || p.plan_code || 'Payment'}</Text>
                <Text style={styles.planMeta}>{fmt(p.paid_at ?? p.created_at)} · {label(p.status)}{p.method ? ` · ${p.method}` : ''}</Text>
              </View>
              <Text style={styles.payAmt}>{money(p.amount)}</Text>
            </View>
          ))}
        </Section>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  current: { backgroundColor: Palette.primary, borderRadius: 18, padding: 20, marginBottom: 16, gap: 4 },
  currentLabel: { color: '#c7d2fe', fontSize: 13, fontWeight: '600' },
  currentName: { color: Palette.white, fontSize: 28, fontWeight: '800' },
  currentMeta: { color: '#e0e7ff', fontSize: 14 },
  warn: { color: '#fde68a', fontSize: 13, fontWeight: '600', marginTop: 4 },
  note: { fontSize: 12, color: Palette.textMuted, textAlign: 'center', marginBottom: 12 },
  plan: { borderWidth: 1, borderColor: Palette.border, borderRadius: 14, padding: 14, marginBottom: 10, gap: 3 },
  planCurrent: { borderColor: Palette.primary, backgroundColor: '#eef2ff' },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  planName: { fontSize: 17, fontWeight: '800', color: Palette.text },
  planPrice: { fontSize: 16, fontWeight: '700', color: Palette.primary },
  planMeta: { fontSize: 13, color: Palette.textMuted },
  feature: { fontSize: 13, color: Palette.text },
  pay: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 },
  payTitle: { fontSize: 14, fontWeight: '600', color: Palette.text },
  payAmt: { fontSize: 14, fontWeight: '800', color: Palette.text },
});
