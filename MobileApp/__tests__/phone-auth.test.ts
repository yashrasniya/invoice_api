import { toE164 } from '@/lib/phone-auth';

describe('toE164', () => {
  it('prefixes a plain 10 digit Indian mobile', () => {
    expect(toE164('98765 43210')).toBe('+919876543210');
    expect(toE164('098765-43210')).toBe('+919876543210');
    expect(toE164('919876543210')).toBe('+919876543210');
  });
  it('keeps an explicit international number', () => {
    expect(toE164('+44 7911 123456')).toBe('+447911123456');
    expect(toE164('+91 98765 43210')).toBe('+919876543210');
  });
  it('rejects numbers that are not valid mobiles', () => {
    expect(toE164('12345')).toBeNull();
    expect(toE164('5876543210')).toBeNull();
    expect(toE164('')).toBeNull();
  });
});
