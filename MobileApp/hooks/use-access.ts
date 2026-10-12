import { useSession } from '@/store/session';

/** True if the company's plan includes this feature code (e.g. 'inventory', 'advanced_reports'). */
export const useFeature = (code: string) =>
  useSession((s) => !!s.access?.features.includes(code));

/** True if the user holds this permission (e.g. 'invoice.view'). Company admins hold role.manage. */
export const useCan = (permission: string) =>
  useSession((s) => !!s.access?.permissions.includes(permission));
