/** Free-trial state, derived from the `subscription` object on `authz/me/`. Pure so it can be unit-tested. */

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
