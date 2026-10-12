import { rangeFor } from '@/services/reports';

describe('rangeFor', () => {
  const now = new Date(2026, 9, 11); // 11 Oct 2026

  it('this month runs from the 1st to today', () => {
    expect(rangeFor('this_month', now)).toEqual({ start_date: '2026-10-01', end_date: '2026-10-11' });
  });
  it('last month is the whole previous month', () => {
    expect(rangeFor('last_month', now)).toEqual({ start_date: '2026-09-01', end_date: '2026-09-30' });
  });
  it('last month wraps over a year boundary', () => {
    expect(rangeFor('last_month', new Date(2026, 0, 15))).toEqual({ start_date: '2025-12-01', end_date: '2025-12-31' });
  });
  it('rolling windows are inclusive of today', () => {
    expect(rangeFor('last_7', now)).toEqual({ start_date: '2026-10-05', end_date: '2026-10-11' });
    expect(rangeFor('last_30', now)).toEqual({ start_date: '2026-09-12', end_date: '2026-10-11' });
  });
  it('the financial year starts on 1 April', () => {
    expect(rangeFor('this_fy', now).start_date).toBe('2026-04-01');
    expect(rangeFor('this_fy', new Date(2026, 1, 10)).start_date).toBe('2025-04-01');   // Feb is still FY 25-26
    expect(rangeFor('this_fy', new Date(2026, 3, 1)).start_date).toBe('2026-04-01');    // 1 Apr starts the new FY
  });
});
