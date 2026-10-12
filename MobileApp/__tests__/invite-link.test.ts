import { parseInviteToken } from '@/lib/invite-link';

describe('parseInviteToken', () => {
  const token = 'Abc123_-xyzABC456defGHI789jklMNO';
  it.each([
    [`https://invoice.orvine.in/app/invite/${token}`],
    [`invoicepro://invite/${token}`],
    [`  https://invoice.orvine.in/app/invite/${token}\n`],
    [token],
  ])('extracts the token from %s', (input) => expect(parseInviteToken(input)).toBe(token));

  it.each([[''], ['   '], ['hello world'], ['https://example.com/other'], ['short']])('rejects %p', (input) =>
    expect(parseInviteToken(input)).toBeNull());
});
