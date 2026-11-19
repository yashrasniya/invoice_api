import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { useCan } from '@/hooks/use-access';
import { planEndingInfo, trialInfo, TrialTone } from '@/lib/trial';
import { useSession } from '@/store/session';

const tones = (theme: Theme): Record<TrialTone, { bg: string; border: string; fg: string }> => ({
  calm: { bg: theme.primarySoft, border: theme.primaryBorder, fg: theme.primaryText },
  soon: { bg: theme.warningSoft, border: theme.warningBorder, fg: theme.warningText },
  last: { bg: theme.dangerSoft, border: theme.dangerBorder, fg: theme.dangerText },
});

/**
 * Home-screen countdown for companies on the free trial, or on a paid plan that is about to stop (won't renew,
 * or a renewal payment failed). Only admins who can manage billing get the upgrade tap;
 * everyone else sees the countdown as plain information (they can't act on it, so no dead button).
 */
export function TrialBanner() {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const subscription = useSession((s) => s.access?.subscription);
  const canManage = useCan('subscription.manage');
  const trial = trialInfo(subscription);
  const ending = trial ? null : planEndingInfo(subscription);
  const info = trial ?? ending;
  if (!info) return null;

  const t = tones(theme)[info.tone];
  const cta = trial ? 'Upgrade' : ending?.kind === 'past_due' ? 'Update payment' : 'Renew';
  const body = trial
    ? canManage
      ? 'Upgrade any time — you keep every remaining trial day, and your first charge is when the trial ends.'
      : 'Ask your company admin to upgrade to keep Pro features after the trial.'
    : ending?.kind === 'past_due'
      ? canManage
        ? "We couldn't charge your renewal. Update your payment to keep your plan's features."
        : "The renewal payment failed. Ask your company admin to update it to keep your plan's features."
      : canManage
        ? "It won't renew on its own. Renew to keep your plan's features; after it ends you move to Free."
        : "It won't renew on its own. Ask your company admin to renew it to keep your plan's features.";

  const content = (
    <>
      <View style={styles.head}>
        <Ionicons name={info.tone === 'calm' ? 'time-outline' : 'alert-circle-outline'} size={18} color={t.fg} />
        <Text style={[styles.title, { color: t.fg }]}>{info.title}</Text>
      </View>
      <Text style={[styles.body, { color: t.fg }]}>{body}</Text>
      {canManage && (
        <View style={styles.cta}>
          <Text style={styles.ctaText}>{cta}</Text>
          <Ionicons name="arrow-forward" size={14} color={theme.onPrimary} />
        </View>
      )}
    </>
  );

  const style = [styles.card, { backgroundColor: t.bg, borderColor: t.border }];
  return canManage ? (
    <TouchableOpacity style={style} activeOpacity={0.85} onPress={() => router.push('/billing')} accessibilityRole="button" accessibilityLabel={`${info.title}. ${cta}`}>
      {content}
    </TouchableOpacity>
  ) : (
    <View style={style} accessibilityRole="summary">{content}</View>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 16, padding: 14, marginBottom: 16, gap: 6 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 15, fontWeight: '800', flex: 1 },
  body: { fontSize: 13, lineHeight: 18 },
  cta: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', backgroundColor: t.primary, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 7, marginTop: 4 },
  ctaText: { color: t.onPrimary, fontSize: 13, fontWeight: '800' },
});
