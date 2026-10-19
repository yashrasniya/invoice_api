import { trialInfo } from '@/lib/trial';

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
