import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { trialInfo, TrialTone } from '@/lib/trial';
import { useSession } from '@/store/session';

const TONES: Record<TrialTone, { bg: string; border: string; fg: string }> = {
  calm: { bg: '#eef2ff', border: '#c7d2fe', fg: '#3730a3' },
  soon: { bg: '#fffbeb', border: '#fde68a', fg: '#92400e' },
  last: { bg: '#fef2f2', border: '#fecaca', fg: '#991b1b' },
};

/**
 * Home-screen countdown for companies on the free trial. Only admins who can manage billing get the upgrade tap;
 * everyone else sees the countdown as plain information (they can't act on it, so no dead button).
 */
export function TrialBanner() {
  const subscription = useSession((s) => s.access?.subscription);
  const canManage = useCan('subscription.manage');
  const trial = trialInfo(subscription);
  if (!trial) return null;

  const t = TONES[trial.tone];
  const body = canManage
    ? 'Upgrade any time — you keep every remaining trial day, and your first charge is when the trial ends.'
    : 'Ask your company admin to upgrade to keep Pro features after the trial.';

  const content = (
    <>
      <View style={styles.head}>
        <Ionicons name={trial.tone === 'calm' ? 'time-outline' : 'alert-circle-outline'} size={18} color={t.fg} />
        <Text style={[styles.title, { color: t.fg }]}>{trial.title}</Text>
      </View>
      <Text style={[styles.body, { color: t.fg }]}>{body}</Text>
      {canManage && (
        <View style={styles.cta}>
          <Text style={styles.ctaText}>Upgrade</Text>
          <Ionicons name="arrow-forward" size={14} color={Palette.white} />
        </View>
      )}
    </>
  );

  const style = [styles.card, { backgroundColor: t.bg, borderColor: t.border }];
  return canManage ? (
    <TouchableOpacity style={style} activeOpacity={0.85} onPress={() => router.push('/billing')} accessibilityRole="button" accessibilityLabel={`${trial.title}. Upgrade`}>
      {content}
    </TouchableOpacity>
  ) : (
    <View style={style} accessibilityRole="summary">{content}</View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 16, padding: 14, marginBottom: 16, gap: 6 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 15, fontWeight: '800', flex: 1 },
  body: { fontSize: 13, lineHeight: 18 },
  cta: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', backgroundColor: Palette.primary, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 7, marginTop: 4 },
  ctaText: { color: Palette.white, fontSize: 13, fontWeight: '800' },
});
