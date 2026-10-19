import { mobileDigits } from '@/lib/mobile';
import { passwordFeedback } from '@/lib/password';
import { apiErrorCode, fieldErrors } from '@/services/api';

const http = (data: unknown, status = 400) => ({ response: { status, data } });

describe('mobileDigits', () => {
  it('trims pasted formats down to the 10 digit number', () => {
    expect(mobileDigits('+91 98765 43210')).toBe('9876543210');
    expect(mobileDigits('098765-43210')).toBe('9876543210');
    expect(mobileDigits('98765 43210')).toBe('9876543210');
    expect(mobileDigits('9876543210123')).toBe('9876543210');
  });
});

describe('passwordFeedback', () => {
  it('counts down to the minimum length', () => {
    expect(passwordFeedback('abc').message).toMatch(/5 more characters/);
    expect(passwordFeedback('abcdefg').message).toMatch(/1 more character to go/);
  });
  it('flags what the server would reject', () => {
    expect(passwordFeedback('password123').ok).toBe(false);
    expect(passwordFeedback('48291736').message).toMatch(/numbers only/i);
    expect(passwordFeedback('asha-rao-2026', { name: 'Asha Rao' }).message).toMatch(/name or email/i);
    expect(passwordFeedback('mypassword-kiran9', { email: 'kiran.s@x.com' }).ok).toBe(true);
  });
  it('accepts a reasonable password', () => {
    expect(passwordFeedback('tulip-orbit-77')).toEqual({ ok: true, message: 'Looks good' });
  });
});

describe('fieldErrors', () => {
  it('returns the first message per field and skips non-field keys', () => {
    const e = http({ email: ['An account with this email already exists.'], password: ['Too common.', 'Too short.'], code: 'email_exists' });
    expect(fieldErrors(e)).toEqual({ email: 'An account with this email already exists.', password: 'Too common.' });
  });
  it('is empty for non-field shaped errors', () => {
    expect(fieldErrors(http({ detail: 'Nope' }))).toEqual({});
    expect(fieldErrors(http(['x']))).toEqual({});
    expect(fieldErrors({ message: 'Network Error' })).toEqual({});
  });
  it('exposes the backend error code', () => {
    expect(apiErrorCode(http({ email: ['x'], code: 'email_exists' }))).toBe('email_exists');
    expect(apiErrorCode(http({ email: ['x'] }))).toBeUndefined();
  });
});
