import { planEndingInfo, trialInfo } from '@/lib/trial';

const sub = (status: string, end_date: string) => ({ status, end_date, plan_code: 'pro' });
const at = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h);

describe('trialInfo', () => {
  it('is null unless the company is trialing', () => {
    expect(trialInfo(null)).toBeNull();
    expect(trialInfo(sub('active', '2026-11-03'), at(2026, 10, 19))).toBeNull();
    expect(trialInfo({ status: 'trialing' }, at(2026, 10, 19))).toBeNull();
    expect(trialInfo(sub('trialing', 'garbage'), at(2026, 10, 19))).toBeNull();
  });

  it('counts whole calendar days and ignores time of day', () => {
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 10, 19, 0))?.daysLeft).toBe(15);
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 10, 19, 23))?.daysLeft).toBe(15);
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 10, 20))?.daysLeft).toBe(14);
  });

  it('recomputes from the clock, so a stale server count cannot show', () => {
    const s = { ...sub('trialing', '2026-11-03'), trial_days_left: 15 };
    expect(trialInfo(s, at(2026, 10, 30))?.daysLeft).toBe(4);
  });

  it('escalates the tone and words the title', () => {
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 10, 25))).toMatchObject({ daysLeft: 9, tone: 'calm', title: '9 days left in your free trial' });
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 10, 31))).toMatchObject({ daysLeft: 3, tone: 'soon' });
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 11, 2))).toMatchObject({ daysLeft: 1, tone: 'soon', title: '1 day left in your free trial' });
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 11, 3))).toMatchObject({ daysLeft: 0, tone: 'last', title: 'Your free trial ends today' });
  });

  it('hides a lapsed trial instead of showing negative days', () => {
    expect(trialInfo(sub('trialing', '2026-11-03'), at(2026, 11, 4))).toBeNull();
  });
});

describe('planEndingInfo', () => {
  const paid = (status: string, end_date: string, auto_renew?: boolean) => ({ status, end_date, plan_code: 'pro', auto_renew });

  it('is null for trials, Free, renewing plans, and plans far from their end', () => {
    expect(planEndingInfo(null)).toBeNull();
    expect(planEndingInfo(paid('trialing', '2026-11-25', false), at(2026, 11, 20))).toBeNull();
    expect(planEndingInfo({ ...paid('active', '2026-11-25', false), plan_code: 'free' }, at(2026, 11, 20))).toBeNull();
    expect(planEndingInfo(paid('active', '2026-11-25', true), at(2026, 11, 20))).toBeNull();
    expect(planEndingInfo(paid('active', '2026-11-25'), at(2026, 11, 20))).toBeNull(); // older server: no auto_renew
    expect(planEndingInfo(paid('active', '2026-12-31', false), at(2026, 11, 20))).toBeNull();
  });

  it('warns in the last week of a plan that will not renew', () => {
    expect(planEndingInfo(paid('active', '2026-11-27', false), at(2026, 11, 20))).toMatchObject({ kind: 'ending', daysLeft: 7, tone: 'calm', title: 'Your plan ends in 7 days' });
    expect(planEndingInfo(paid('active', '2026-11-21', false), at(2026, 11, 20))).toMatchObject({ daysLeft: 1, tone: 'soon', title: 'Your plan ends in 1 day' });
    expect(planEndingInfo(paid('active', '2026-11-20', false), at(2026, 11, 20))).toMatchObject({ daysLeft: 0, tone: 'last', title: 'Your plan ends today' });
  });

  it('counts a failed renewal down to the end of the grace period', () => {
    expect(planEndingInfo(paid('past_due', '2026-11-18', true), at(2026, 11, 20))).toMatchObject({ kind: 'past_due', daysLeft: 5, tone: 'soon' });
    expect(planEndingInfo(paid('past_due', '2026-11-13', true), at(2026, 11, 20))).toMatchObject({ daysLeft: 0, tone: 'last', title: 'Payment failed: your plan stops today' });
    expect(planEndingInfo(paid('past_due', '2026-11-12', true), at(2026, 11, 20))).toBeNull();
  });
});
