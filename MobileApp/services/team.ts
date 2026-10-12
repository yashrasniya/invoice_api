import api from './api';

export type Member = { id: number; username: string; first_name: string; last_name: string; email: string; is_company_admin: boolean };
export type Role = {
  id: number; name: string; description: string; is_system_role: boolean;
  permission_codes: string[]; user_names: { id: number; username: string }[];
};
export type Invite = {
  id: number; email: string; role: number | null; role_name: string | null; status: string;
  invited_by_name: string | null; created_at: string; expires_at: string; invite_link: string | null;
};
export type AuditEntry = {
  id: number; user_name: string | null; action: string; resource_type: string; resource_id: string | null;
  new_data: Record<string, unknown> | null; timestamp: string;
};

// these list endpoints are unpaginated; tolerate a page wrapper if that changes
const rows = <T,>(d: T[] | { results: T[] }): T[] => (Array.isArray(d) ? d : d.results);

export const fetchMembers = async () => rows((await api.get<Member[]>('authz/users/')).data);
export const fetchRoles = async () => rows((await api.get<Role[]>('authz/roles/')).data);
export const assignRole = (roleId: number, userId: number) => api.post(`authz/roles/${roleId}/users/`, { user_id: userId });
export const unassignRole = (roleId: number, userId: number) => api.delete(`authz/roles/${roleId}/users/${userId}/`);

export const fetchInvites = async () => rows((await api.get<Invite[]>('authz/invites/')).data);
export const createInvite = async (email: string, role: number | null) =>
  (await api.post<Invite & { mail_sent: boolean }>('authz/invites/', { email, ...(role ? { role } : {}) })).data;
export const resendInvite = async (id: number) => (await api.post<{ mail_sent: boolean }>(`authz/invites/${id}/resend/`)).data;
export const revokeInvite = (id: number) => api.delete(`authz/invites/${id}/`);

export const fetchAudit = async () => rows((await api.get<AuditEntry[]>('authz/audit-log/')).data);
