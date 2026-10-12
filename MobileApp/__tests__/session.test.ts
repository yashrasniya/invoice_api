const mem: Record<string, string> = {};
jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(async (k: string) => (k in mem ? mem[k] : null)),
    setItem: jest.fn(async (k: string, v: string) => { mem[k] = v; }),
    removeItem: jest.fn(async (k: string) => { delete mem[k]; }),
  },
}));
jest.mock('@/services/token-storage', () => ({ getToken: jest.fn(), setToken: jest.fn(), clearToken: jest.fn() }));
jest.mock('@/services/auth', () => ({ fetchProfile: jest.fn(), fetchAccess: jest.fn(), logoutRequest: jest.fn() }));
jest.mock('@/lib/push', () => ({ unregisterPush: jest.fn() }));

import { fetchAccess, fetchProfile } from '@/services/auth';
import { clearToken, getToken } from '@/services/token-storage';
import { useSession } from '@/store/session';

const user = { username: 'demo', name: 'Demo', is_company_varified: true } as any;
const access = { company_name: 'Demo Co', permissions: ['invoice.view'], features: ['inventory'] } as any;
const http = (status: number) => ({ response: { status } });
const net = () => ({ message: 'Network Error' });

beforeEach(() => {
  for (const k of Object.keys(mem)) delete mem[k];
  jest.clearAllMocks();
  useSession.setState({ status: 'loading', user: null, access: null });
});

describe('session bootstrap', () => {
  it('is signed out when no token is stored', async () => {
    (getToken as jest.Mock).mockResolvedValue(null);
    await useSession.getState().bootstrap();
    expect(useSession.getState().status).toBe('signedOut');
  });

  it('signs in and remembers the account on success', async () => {
    (getToken as jest.Mock).mockResolvedValue('tok');
    (fetchProfile as jest.Mock).mockResolvedValue(user);
    (fetchAccess as jest.Mock).mockResolvedValue(access);
    await useSession.getState().bootstrap();
    expect(useSession.getState()).toMatchObject({ status: 'signedIn', access });
    expect(JSON.parse(mem['session-snapshot-v1'])).toMatchObject({ access });
  });

  it('a rejected token ends the session and forgets the snapshot', async () => {
    mem['session-snapshot-v1'] = JSON.stringify({ user, access });
    (getToken as jest.Mock).mockResolvedValue('stale');
    (fetchProfile as jest.Mock).mockRejectedValue(http(401));
    (fetchAccess as jest.Mock).mockRejectedValue(http(401));
    await useSession.getState().bootstrap();
    expect(useSession.getState().status).toBe('signedOut');
    expect(clearToken).toHaveBeenCalled();
    expect(mem['session-snapshot-v1']).toBeUndefined();
  });

  it('offline with a saved snapshot: stays signed in with the last known permissions', async () => {
    mem['session-snapshot-v1'] = JSON.stringify({ user, access });
    (getToken as jest.Mock).mockResolvedValue('tok');
    (fetchProfile as jest.Mock).mockRejectedValue(net());
    (fetchAccess as jest.Mock).mockRejectedValue(net());
    await useSession.getState().bootstrap();
    expect(useSession.getState()).toMatchObject({ status: 'signedIn', access });
    expect(clearToken).not.toHaveBeenCalled();
  });

  it('offline with nothing saved: shows the retry state, never a permissionless signed-in app', async () => {
    (getToken as jest.Mock).mockResolvedValue('tok');
    (fetchProfile as jest.Mock).mockRejectedValue(net());
    (fetchAccess as jest.Mock).mockRejectedValue(net());
    await useSession.getState().bootstrap();
    expect(useSession.getState().status).toBe('error');
    expect(clearToken).not.toHaveBeenCalled();
  });

  it('a server error (500) is treated like being offline, not like a logout', async () => {
    (getToken as jest.Mock).mockResolvedValue('tok');
    (fetchProfile as jest.Mock).mockRejectedValue(http(500));
    (fetchAccess as jest.Mock).mockRejectedValue(http(500));
    await useSession.getState().bootstrap();
    expect(useSession.getState().status).toBe('error');
    expect(clearToken).not.toHaveBeenCalled();
  });

  it('retry after a failure recovers', async () => {
    (getToken as jest.Mock).mockResolvedValue('tok');
    (fetchProfile as jest.Mock).mockRejectedValueOnce(net()).mockResolvedValue(user);
    (fetchAccess as jest.Mock).mockRejectedValueOnce(net()).mockResolvedValue(access);
    await useSession.getState().bootstrap();
    expect(useSession.getState().status).toBe('error');
    await useSession.getState().bootstrap();
    expect(useSession.getState().status).toBe('signedIn');
  });
});
