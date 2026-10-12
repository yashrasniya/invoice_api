import { errorMessage, isOfflineError } from '@/services/api';

const http = (data: unknown, status = 400) => ({ response: { status, data } });

describe('errorMessage', () => {
  it('reads each shape the backend uses', () => {
    expect(errorMessage(http({ detail: 'Plan limit reached.' }))).toBe('Plan limit reached.');
    expect(errorMessage(http({ error: 'password is wrong!' }))).toBe('password is wrong!');
    expect(errorMessage(http({ email: ['This user is already in your company.'] }))).toBe('email: This user is already in your company.');
    expect(errorMessage(http({ non_field_errors: ['Nope'] }))).toBe('Nope');
    expect(errorMessage(http(['Only pending invites can be revoked.']))).toBe('Only pending invites can be revoked.');
    expect(errorMessage(http('Bad gateway'))).toBe('Bad gateway');
  });
  it('does not dump an HTML error page on the user', () => {
    expect(errorMessage(http('<html>' + 'x'.repeat(500)), 'fallback')).toBe('fallback');
  });
  it('explains a network failure', () => {
    expect(errorMessage({ message: 'Network Error' })).toMatch(/cannot reach the server/i);
    expect(errorMessage({ code: 'ECONNABORTED' })).toMatch(/cannot reach the server/i);
  });
  it('falls back for unknown errors', () => {
    expect(errorMessage(new Error('boom'), 'fallback')).toBe('fallback');
  });
});

describe('isOfflineError', () => {
  it('is true only when the request never reached the server', () => {
    expect(isOfflineError({ message: 'Network Error' })).toBe(true);
    expect(isOfflineError({ code: 'ECONNABORTED' })).toBe(true);
    expect(isOfflineError({ code: 'ERR_NETWORK' })).toBe(true);
  });
  it('is false when the server answered, even with an error', () => {
    expect(isOfflineError(http({ detail: 'nope' }, 400))).toBe(false);
    expect(isOfflineError(http({}, 500))).toBe(false);
    expect(isOfflineError({ response: { status: 403 }, code: 'ERR_NETWORK' })).toBe(false);
  });
  it('is false for unrelated errors', () => {
    expect(isOfflineError(new Error('boom'))).toBe(false);
    expect(isOfflineError(undefined)).toBe(false);
  });
});
