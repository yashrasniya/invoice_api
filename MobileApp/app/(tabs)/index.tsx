import React, { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQuery } from '@tanstack/react-query';
import { FirstRunChecklist, ONBOARDING_KEY } from '@/components/first-run-checklist';
import { TrialBanner } from '@/components/trial-banner';
import { VerifyEmailBanner } from '@/components/verify-email-banner';
import { BarChart, HBarList } from '@/components/charts';
import { PeriodBar, Section } from '@/components/report-ui';
import { ProUpsell } from '@/components/pro-upsell';
import { StatusBadge } from '@/components/ui/bits';
import { Button } from '@/components/ui/button';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { compactInr, money } from '@/lib/invoice-calc';
import { errorMessage } from '@/services/api';
import { DASHBOARD_RANGES, DashboardRange, fetchDashboard, fetchDashboardWidgets } from '@/services/auth';
import type { PaymentStatus } from '@/services/invoices';
import { fetchOnboarding } from '@/services/onboarding';
import { useSession } from '@/store/session';

const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardLabel}>{label}</Text>
      <Text style={[styles.cardValue, tone ? { color: tone } : null]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      {!!sub && <Text style={[styles.cardSub, tone ? { color: tone } : null]}>{sub}</Text>}
    </View>
  );
}

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const company = useSession((s) => s.access?.company_name);
  const canCreate = useCan('invoice.create');
  const canViewInvoices = useCan('invoice.view');
  const [range, setRange] = useState<DashboardRange>('this_month');

  const kpis = useQuery({ queryKey: ['dashboard', 'kpis', range], queryFn: () => fetchDashboard(range) });
  const widgets = useQuery({ queryKey: ['dashboard', 'widgets', range], queryFn: () => fetchDashboardWidgets(range) });
  const onboarding = useQuery({ queryKey: ONBOARDING_KEY, queryFn: fetchOnboarding });
  // steps tick off in other screens (new customer, new invoice, share); re-check whenever Home regains focus
  useFocusEffect(React.useCallback(() => { onboarding.refetch(); }, [])); // eslint-disable-line react-hooks/exhaustive-deps
  const k = kpis.data;
  const w = widgets.data;

  const refresh = () => { kpis.refetch(); widgets.refetch(); onboarding.refetch(); };
  const trendHasData = !!w && w.trend.some((t) => t.total > 0);
  const growth = k?.percentage_change;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={{ paddingTop: insets.top + 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={kpis.isRefetching || widgets.isRefetching} onRefresh={refresh} />}>
      <View style={styles.pad}>
        <Text style={styles.greeting}>Hello{k?.name?.trim() ? `, ${k.name.trim().split(' ')[0]}` : ''} 👋</Text>
        {!!company && <Text style={styles.company}>{company}</Text>}
      </View>

      <PeriodBar options={DASHBOARD_RANGES} value={range} onChange={setRange} />

      <View style={styles.pad}>
        <TrialBanner />
        <VerifyEmailBanner />
        <FirstRunChecklist data={onboarding.data} />
        {/* an upgrade pitch before the first invoice competes with the one thing a new user should do */}
        {k?.has_any_invoice && <ProUpsell />}
        {!!kpis.error && !k && <Text style={styles.error}>{errorMessage(kpis.error)}</Text>}

        {k && (
          <>
            <View style={styles.grid}>
              <Stat
                label="Sales" value={money(k.month_total_final_amount).replace('.00', '')}
                sub={growth == null ? `${k.invoices_this_month_count} invoices` : `${growth >= 0 ? '▲' : '▼'} ${Math.abs(growth)}% vs previous · ${k.invoices_this_month_count} inv.`}
                tone={growth != null && growth < 0 ? Palette.danger : growth != null ? Palette.success : undefined}
              />
              <Stat label="GST collected" value={money(k.month_gst_final_amount).replace('.00', '')} />
              <Stat label="Receivable" value={money(k.receivable_amount).replace('.00', '')} sub={`${k.receivable_count} unpaid`} />
              <Stat label="Overdue" value={money(k.overdue_amount).replace('.00', '')} sub={`${k.overdue_count} overdue`}
                tone={k.overdue_count > 0 ? Palette.danger : undefined} />
            </View>

            {!k.has_any_invoice ? (
              <View style={styles.empty}>
                <Text style={styles.emptyTitle}>Create your first invoice</Text>
                <Text style={styles.emptyBody}>Takes about a minute. Your sales and GST numbers will fill in here as you go.</Text>
                {canCreate && <Button title="Create invoice" onPress={() => router.push('/invoice/new')} />}
              </View>
            ) : canCreate && (
              <Button title="New invoice" onPress={() => router.push('/invoice/new')} style={{ marginBottom: 16 }} />
            )}
          </>
        )}

        {w && canViewInvoices && !!k?.has_any_invoice && (
          <>
            <Section title="Sales · last 6 months">
              {trendHasData ? (
                <>
                  <BarChart barWidth={22} data={w.trend.map((t) => ({ label: t.label, values: [t.total] }))} />
                  <View style={styles.trendRow}>
                    {w.trend.map((t) => (
                      <View key={t.month} style={styles.trendCell}>
                        <Text style={styles.trendValue}>{compactInr(t.total)}</Text>
                        <Text style={styles.trendCount}>{t.count} inv.</Text>
                      </View>
                    ))}
                  </View>
                </>
              ) : <Text style={styles.muted}>No sales in the last 6 months.</Text>}
            </Section>

            {w.top_customers.length > 0 && (
              <Section title={`Top customers · ${k?.range_label ?? ''}`}>
                <HBarList items={w.top_customers.map((c) => ({ label: `${c.name} (${c.count})`, value: c.total }))} />
              </Section>
            )}

            {w.payment_methods.length > 0 && (
              <Section title={`Payments received · ${k?.range_label ?? ''}`}>
                <HBarList color={Palette.success} items={w.payment_methods.map((p) => ({ label: titleCase(p.method), value: p.total }))} />
              </Section>
            )}
          </>
        )}

        {w && w.low_stock.length > 0 && (
          <Section title="Low stock">
            {w.low_stock.map((p) => (
              <TouchableOpacity key={p.id} style={styles.row} onPress={() => router.push(`/inventory/${p.id}`)}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{p.name}</Text>
                  <Text style={styles.muted}>{p.sku} · reorder at {p.reorder_level}</Text>
                </View>
                <Text style={[styles.badge, { color: Palette.danger, backgroundColor: '#fee2e2' }]}>{p.current_stock} left</Text>
              </TouchableOpacity>
            ))}
          </Section>
        )}

        {w && w.gst_due.length > 0 && (
          <Section title="GST due dates">
            {w.gst_due.map((g) => (
              <View key={g.form} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{g.form} · {g.period}</Text>
                  <Text style={styles.muted}>Due {new Date(g.due_date).toLocaleDateString()}</Text>
                </View>
                <Text style={[styles.badge, g.days_left < 0
                  ? { color: Palette.danger, backgroundColor: '#fee2e2' }
                  : g.days_left <= 5 ? { color: '#92400e', backgroundColor: '#fef3c7' } : { color: Palette.success, backgroundColor: '#dcfce7' }]}>
                  {g.days_left < 0 ? `${-g.days_left}d overdue` : g.days_left === 0 ? 'Today' : `${g.days_left}d left`}
                </Text>
              </View>
            ))}
          </Section>
        )}

        {w && canViewInvoices && w.recent_invoices.length > 0 && (
          <Section title="Recent invoices">
            {w.recent_invoices.map((i) => (
              <TouchableOpacity key={i.id} style={styles.row} onPress={() => router.push(`/invoice/${i.id}`)}>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.rowTitle} numberOfLines={1}>{i.customer}</Text>
                  <Text style={styles.muted}>#{i.invoice_number}{i.date ? ` · ${i.date}` : ''}</Text>
                </View>
                <View style={{ alignItems: 'flex-end', gap: 4 }}>
                  <Text style={styles.rowTitle}>{money(i.total).replace('.00', '')}</Text>
                  <StatusBadge status={i.payment_status as PaymentStatus} />
                </View>
              </TouchableOpacity>
            ))}
            <TouchableOpacity onPress={() => router.push('/invoices')} style={{ paddingTop: 10 }}>
              <Text style={styles.link}>View all invoices →</Text>
            </TouchableOpacity>
          </Section>
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  pad: { paddingHorizontal: 16 },
  greeting: { fontSize: 26, fontWeight: '800', color: Palette.text },
  company: { fontSize: 15, color: Palette.textMuted, marginTop: 2, marginBottom: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 14, marginBottom: 16 },
  card: { width: '48%', flexGrow: 1, backgroundColor: Palette.white, borderRadius: 16, padding: 16, borderWidth: 1, borderColor: Palette.border },
  cardLabel: { fontSize: 13, color: Palette.textMuted, fontWeight: '600' },
  cardValue: { fontSize: 22, fontWeight: '800', color: Palette.text, marginTop: 6 },
  cardSub: { fontSize: 12, color: Palette.textMuted, marginTop: 4 },
  error: { color: Palette.danger, marginTop: 24 },
  empty: { borderWidth: 1.5, borderStyle: 'dashed', borderColor: Palette.border, borderRadius: 16, padding: 20, marginBottom: 16, alignItems: 'stretch' },
  emptyTitle: { fontSize: 17, fontWeight: '800', color: Palette.text, textAlign: 'center' },
  emptyBody: { fontSize: 14, color: Palette.textMuted, textAlign: 'center', marginTop: 4, marginBottom: 16, lineHeight: 20 },
  muted: { fontSize: 13, color: Palette.textMuted },
  trendRow: { flexDirection: 'row', marginTop: 10 },
  trendCell: { flex: 1, alignItems: 'center' },
  trendValue: { fontSize: 11, fontWeight: '700', color: Palette.text },
  trendCount: { fontSize: 10, color: Palette.textMuted },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: Palette.border },
  rowTitle: { fontSize: 15, fontWeight: '700', color: Palette.text },
  badge: { fontSize: 12, fontWeight: '700', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, overflow: 'hidden' },
  link: { color: Palette.primary, fontWeight: '700', fontSize: 14 },
});
