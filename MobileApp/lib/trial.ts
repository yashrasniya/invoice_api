/** Free-trial and plan-ending state, derived from the `subscription` object on `authz/me/`. Pure so it can be unit-tested. */

export type TrialTone = 'calm' | 'soon' | 'last';
export type TrialInfo = { daysLeft: number; endDate: string; tone: TrialTone; title: string };

/** `YYYY-MM-DD` as a local calendar date (new Date('2026-10-19') would be UTC midnight and slip a day in IST). */
function localDate(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

/**
 * Days left are recomputed from `end_date` against the phone's clock, not read from the server's
 * `trial_days_left`: access is fetched once at sign-in, so a stored count would still say "9 days" tomorrow.
 * Returns null when the company is not on a trial (or the date is unusable).
 */
export function trialInfo(subscription: Record<string, any> | null | undefined, now: Date = new Date()): TrialInfo | null {
  if (!subscription || subscription.status !== 'trialing' || typeof subscription.end_date !== 'string') return null;
  const end = localDate(subscription.end_date);
  if (!end) return null;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const daysLeft = Math.round((end.getTime() - today.getTime()) / 86_400_000);
  if (daysLeft < 0) return null; // lapsed; the server's expiry job moves it to Free

  const tone: TrialTone = daysLeft === 0 ? 'last' : daysLeft <= 3 ? 'soon' : 'calm';
  const title =
    daysLeft === 0 ? 'Your free trial ends today' :
    daysLeft === 1 ? '1 day left in your free trial' :
    `${daysLeft} days left in your free trial`;
  return { daysLeft, endDate: subscription.end_date, tone, title };
}

/** Days of warning before a paid plan that won't renew ends. */
export const PLAN_ENDING_WARN_DAYS = 7;
/** Matches CompanySubscription.GRACE_PERIOD_DAYS: a past_due plan keeps working this long after end_date. */
export const PAST_DUE_GRACE_DAYS = 7;

export type PlanEndingInfo = { kind: 'ending' | 'past_due'; daysLeft: number; endDate: string; tone: TrialTone; title: string };

const plural = (n: number) => (n === 1 ? '1 day' : `${n} days`);

/**
 * A paid plan that is about to stop: either it won't auto-renew and ends within PLAN_ENDING_WARN_DAYS, or a
 * renewal charge failed (`past_due`) and the grace period is running out. Null for trials (see trialInfo),
 * the Free plan, and plans that renew on their own. A missing `auto_renew` (older server) counts as renewing.
 */
export function planEndingInfo(subscription: Record<string, any> | null | undefined, now: Date = new Date()): PlanEndingInfo | null {
  if (!subscription || typeof subscription.end_date !== 'string' || subscription.plan_code === 'free') return null;
  const end = localDate(subscription.end_date);
  if (!end) return null;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  if (subscription.status === 'past_due') {
    const graceEnd = new Date(end.getFullYear(), end.getMonth(), end.getDate() + PAST_DUE_GRACE_DAYS);
    const daysLeft = Math.round((graceEnd.getTime() - today.getTime()) / 86_400_000);
    if (daysLeft < 0) return null;
    return { kind: 'past_due', daysLeft, endDate: subscription.end_date, tone: daysLeft <= 1 ? 'last' : 'soon',
      title: daysLeft === 0 ? 'Payment failed: your plan stops today' : `Payment failed: your plan stops in ${plural(daysLeft)}` };
  }

  if (subscription.status !== 'active' || subscription.auto_renew !== false) return null;
  const daysLeft = Math.round((end.getTime() - today.getTime()) / 86_400_000);
  if (daysLeft < 0 || daysLeft > PLAN_ENDING_WARN_DAYS) return null;
  return { kind: 'ending', daysLeft, endDate: subscription.end_date,
    tone: daysLeft === 0 ? 'last' : daysLeft <= 3 ? 'soon' : 'calm',
    title: daysLeft === 0 ? 'Your plan ends today' : `Your plan ends in ${plural(daysLeft)}` };
}
