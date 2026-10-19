import { addDaysYmd, daysBetweenYmd, dueAfterDateChange, parseYmd, PAYMENT_TERMS, termDays, ymd } from '@/lib/invoice-dates';

describe('date strings', () => {
  it('round-trips through a Date without drifting a day', () => {
    expect(ymd(parseYmd('2026-03-29'))).toBe('2026-03-29');
    expect(ymd(parseYmd('2026-10-25'))).toBe('2026-10-25');   // around daylight-saving changes
  });

  it('adds days across month, year and leap-year boundaries', () => {
    expect(addDaysYmd('2026-08-10', 15)).toBe('2026-08-25');
    expect(addDaysYmd('2026-08-20', 15)).toBe('2026-09-04');
    expect(addDaysYmd('2026-12-20', 30)).toBe('2027-01-19');
    expect(addDaysYmd('2024-02-20', 15)).toBe('2024-03-06');
    expect(addDaysYmd('2026-08-10', 0)).toBe('2026-08-10');
  });

  it('counts whole days between dates', () => {
    expect(daysBetweenYmd('2026-08-10', '2026-08-25')).toBe(15);
    expect(daysBetweenYmd('2026-08-25', '2026-08-10')).toBe(-15);
    expect(daysBetweenYmd('2026-03-28', '2026-03-30')).toBe(2);       // DST weekend
    expect(daysBetweenYmd('', '2026-08-10')).toBeNull();
    expect(daysBetweenYmd('2026-08-10', 'soon')).toBeNull();
  });

  it('leaves an unparseable date alone instead of producing garbage', () => {
    expect(addDaysYmd('nonsense', 5)).toBe('nonsense');
  });
});

describe('payment terms', () => {
  it('offers the same shortcuts as the web editor', () => {
    expect(PAYMENT_TERMS.map((t) => t.days)).toEqual([0, 7, 15, 30, 45, 60]);
    expect(PAYMENT_TERMS[0].label).toBe('Due on receipt');
    expect(PAYMENT_TERMS[2].label).toBe('Net 15');
  });

  it('reads the term back from the two dates', () => {
    expect(termDays('2026-08-10', '2026-08-25')).toBe(15);
    expect(termDays('2026-08-10', null)).toBeNull();
  });
});

describe('moving the invoice date', () => {
  it('carries the due date so Net 15 stays Net 15', () => {
    expect(dueAfterDateChange('2026-08-10', '2026-09-01', '2026-08-25')).toBe('2026-09-16');
  });

  it('never ends up due before it is issued', () => {
    // a due date that was already before the invoice date is pulled up to the new date
    expect(dueAfterDateChange('2026-08-10', '2026-09-01', '2026-08-01')).toBe('2026-09-01');
  });

  it('has nothing to carry without a due date', () => {
    expect(dueAfterDateChange('2026-08-10', '2026-09-01', null)).toBeNull();
  });
});
