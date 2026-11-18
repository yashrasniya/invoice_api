import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { useCan } from '@/hooks/use-access';
import { useIsFreePlan } from '@/hooks/use-plan';
import { money } from '@/lib/invoice-calc';
import { fetchPlans } from '@/services/billing';
import { useSession } from '@/store/session';

/**
 * Shown to free-plan admins on Home: the cheapest paid plan, a few of the features they don't have yet, and a way
 * to upgrade in two taps — this card opens Plan & billing, whose button opens checkout.
 */
export function ProUpsell() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const isFree = useIsFreePlan();
  const canManage = useCan('subscription.manage');
  const features = useSession((s) => s.access?.features);
  const plans = useQuery({ queryKey: ['billing-plans'], queryFn: fetchPlans, enabled: isFree && canManage });

  if (!isFree || !canManage) return null;
  const pro = (plans.data ?? [])
    .filter((p) => Number(p.monthly_price) > 0)
    .sort((a, b) => Number(a.monthly_price) - Number(b.monthly_price))[0];
  if (!pro) return null;

  const missing = pro.features.filter((f) => !features?.includes(f.code)).slice(0, 4);
  const price = `${money(pro.monthly_price).replace('.00', '')}/mo`;

  return (
    <TouchableOpacity style={styles.card} activeOpacity={0.9} onPress={() => router.push('/billing')} accessibilityRole="button">
      <View style={styles.head}>
        <View style={styles.badge}><Ionicons name="sparkles" size={14} color={theme.primary} /><Text style={styles.badgeText}>NEW</Text></View>
        <Text style={styles.price}>{price}</Text>
      </View>
      <Text style={styles.title}>Upgrade to {pro.name}</Text>
      <Text style={styles.sub}>Features you might like</Text>
      {missing.map((f) => (
        <View key={f.code} style={styles.row}>
          <Ionicons name="checkmark-circle" size={16} color={theme.onHeroMuted} />
          <Text style={styles.feature}>{f.name}</Text>
        </View>
      ))}
      <View style={styles.cta}>
        <Text style={styles.ctaText}>See plan · 2 taps to upgrade</Text>
        <Ionicons name="arrow-forward" size={16} color={theme.primary} />
      </View>
    </TouchableOpacity>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  card: { backgroundColor: t.hero, borderRadius: 18, padding: 18, marginBottom: 16, gap: 6 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: t.surface, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  badgeText: { color: t.primary, fontSize: 11, fontWeight: '800' },
  price: { color: t.onHeroMuted, fontSize: 14, fontWeight: '700' },
  title: { color: t.onHero, fontSize: 22, fontWeight: '800', marginTop: 4 },
  sub: { color: t.onHeroMuted, fontSize: 13, marginBottom: 2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  feature: { color: t.onHero, fontSize: 14, flex: 1 },
  cta: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: t.surface, borderRadius: 12, paddingVertical: 12, marginTop: 10 },
  ctaText: { color: t.primary, fontSize: 15, fontWeight: '800' },
});
