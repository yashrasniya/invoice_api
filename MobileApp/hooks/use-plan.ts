import { useSession } from '@/store/session';

/** True once access has loaded and the company is on the free plan (or has no working subscription). */
export const useIsFreePlan = () =>
  useSession((s) => !!s.access && (!s.access.subscription?.plan_code || s.access.subscription.plan_code === 'free'));
