import React, { useState } from 'react';
import { Alert, FlatList, Modal, RefreshControl, Share, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Stack } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PeriodBar } from '@/components/report-ui';
import { Button } from '@/components/ui/button';
import { Centered, Chip, EmptyState } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { errorMessage } from '@/services/api';
import {
  assignRole, createInvite, fetchAudit, fetchInvites, fetchMembers, fetchRoles, Invite, Member, resendInvite,
  revokeInvite, Role, unassignRole,
} from '@/services/team';
import { useSession } from '@/store/session';

type Tab = 'members' | 'invites' | 'roles' | 'activity';
const when = (d: string) => new Date(d).toLocaleString();
const title = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

export default function TeamScreen() {
  const qc = useQueryClient();
  const isAdmin = useCan('role.manage');
  const canInvite = useCan('user.invite');
  const me = useSession((s) => s.user?.username);
  const [tab, setTab] = useState<Tab>(isAdmin ? 'members' : 'invites');
  const [editing, setEditing] = useState<Member | null>(null);
  const [inviting, setInviting] = useState(false);

  const members = useQuery({ queryKey: ['team-members'], queryFn: fetchMembers, enabled: isAdmin });
  const roles = useQuery({ queryKey: ['team-roles'], queryFn: fetchRoles, enabled: isAdmin || canInvite });
  const invites = useQuery({ queryKey: ['team-invites'], queryFn: fetchInvites, enabled: canInvite });
  const audit = useQuery({ queryKey: ['team-audit'], queryFn: fetchAudit, enabled: isAdmin && tab === 'activity' });

  const options: { value: Tab; label: string }[] = [
    ...(isAdmin ? [{ value: 'members' as Tab, label: 'Members' }] : []),
    ...(canInvite ? [{ value: 'invites' as Tab, label: 'Invites' }] : []),
    ...(isAdmin ? [{ value: 'roles' as Tab, label: 'Roles' }, { value: 'activity' as Tab, label: 'Activity' }] : []),
  ];

  const resend = useMutation({
    mutationFn: resendInvite,
    onSuccess: (r) => Alert.alert(r.mail_sent ? 'Invite re-sent' : 'Email not sent', r.mail_sent ? 'The invitation email was sent again.' : 'Email delivery failed — share the link instead.'),
    onError: (e) => Alert.alert('Could not resend', errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: revokeInvite,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['team-invites'] }),
    onError: (e) => Alert.alert('Could not revoke', errorMessage(e)),
  });

  if (!isAdmin && !canInvite) {
    return <><Stack.Screen options={{ title: 'Team' }} /><EmptyState icon="lock-closed-outline" title="No access" hint="Only admins can manage the team." /></>;
  }

  const rolesFor = (u: Member) => (roles.data ?? []).filter((r) => r.user_names.some((x) => x.id === u.id));

  const listProps = (q: { isLoading: boolean; isRefetching: boolean; refetch: () => unknown; error: unknown }) => ({
    refreshControl: <RefreshControl refreshing={q.isRefetching} onRefresh={() => { void q.refetch(); }} />,
    contentContainerStyle: { padding: 16, paddingBottom: 40, flexGrow: 1 },
  });

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: 'Team & access' }} />
      <PeriodBar options={options} value={tab} onChange={setTab} />

      {tab === 'members' && (members.isLoading ? <Centered /> : (
        <FlatList {...listProps(members)} data={members.data ?? []} keyExtractor={(m) => String(m.id)}
          ListEmptyComponent={<EmptyState icon="people-outline" title="No members" hint={errorMessage(members.error)} />}
          renderItem={({ item }) => (
            <TouchableOpacity style={styles.card} onPress={() => setEditing(item)}>
              <View style={styles.avatar}><Text style={styles.avatarText}>{(item.first_name?.[0] ?? item.username[0]).toUpperCase()}</Text></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{[item.first_name, item.last_name].filter(Boolean).join(' ') || item.username}{item.username === me ? ' (you)' : ''}</Text>
                <Text style={styles.meta}>{item.email}</Text>
                <Text style={styles.roles}>{rolesFor(item).map((r) => r.name).join(', ') || 'No role'}</Text>
              </View>
            </TouchableOpacity>
          )} />
      ))}

      {tab === 'invites' && (invites.isLoading ? <Centered /> : (
        <>
          <FlatList {...listProps(invites)} data={invites.data ?? []} keyExtractor={(i) => String(i.id)}
            ListEmptyComponent={<EmptyState icon="mail-outline" title="No invites" hint={errorMessage(invites.error, 'Tap Invite to add someone.')} />}
            renderItem={({ item }) => <InviteCard invite={item}
              onResend={() => resend.mutate(item.id)}
              onRevoke={() => Alert.alert('Revoke invite', `Cancel the invitation to ${item.email}?`, [
                { text: 'Keep', style: 'cancel' }, { text: 'Revoke', style: 'destructive', onPress: () => revoke.mutate(item.id) }])} />} />
          {canInvite && <View style={styles.footer}><Button title="Invite someone" onPress={() => setInviting(true)} /></View>}
        </>
      ))}

      {tab === 'roles' && (roles.isLoading ? <Centered /> : (
        <FlatList {...listProps(roles)} data={roles.data ?? []} keyExtractor={(r) => String(r.id)}
          renderItem={({ item }) => (
            <View style={styles.cardCol}>
              <Text style={styles.name}>{item.name}{item.is_system_role ? '  · built-in' : ''}</Text>
              {!!item.description && <Text style={styles.meta}>{item.description}</Text>}
              <Text style={styles.meta}>{item.user_names.length} member{item.user_names.length === 1 ? '' : 's'} · {item.permission_codes.length} permissions</Text>
              <Text style={styles.perms}>{item.permission_codes.join(', ') || 'No permissions'}</Text>
            </View>
          )}
          ListFooterComponent={<Text style={styles.foot}>Create or edit custom roles on the web.</Text>} />
      ))}

      {tab === 'activity' && (audit.isLoading ? <Centered /> : (
        <FlatList {...listProps(audit)} data={audit.data ?? []} keyExtractor={(a) => String(a.id)}
          ListEmptyComponent={<EmptyState icon="time-outline" title="No activity yet" hint={errorMessage(audit.error, '')} />}
          renderItem={({ item }) => (
            <View style={styles.cardCol}>
              <Text style={styles.name}>{title(item.action)} · {title(item.resource_type)}</Text>
              <Text style={styles.meta}>{item.user_name ?? 'System'} · {when(item.timestamp)}</Text>
            </View>
          )} />
      ))}

      {editing && <RoleEditor member={editing} roles={roles.data ?? []} onClose={() => setEditing(null)}
        onChanged={() => { qc.invalidateQueries({ queryKey: ['team-roles'] }); }} />}
      {inviting && <InviteModal roles={roles.data ?? []} onClose={() => setInviting(false)}
        onDone={() => { setInviting(false); qc.invalidateQueries({ queryKey: ['team-invites'] }); }} />}
    </View>
  );
}

function InviteCard({ invite, onResend, onRevoke }: { invite: Invite; onResend: () => void; onRevoke: () => void }) {
  const pending = invite.status === 'pending';
  return (
    <View style={styles.cardCol}>
      <Text style={styles.name}>{invite.email}</Text>
      <Text style={styles.meta}>{title(invite.status)} · {invite.role_name ?? 'Member'} · expires {new Date(invite.expires_at).toLocaleDateString()}</Text>
      {pending && (
        <View style={styles.actions}>
          <TouchableOpacity onPress={onResend}><Text style={styles.link}>Resend</Text></TouchableOpacity>
          {!!invite.invite_link && (
            <TouchableOpacity onPress={() => Share.share({ message: `Join us on Orvine Invoice: ${invite.invite_link}` })}><Text style={styles.link}>Share link</Text></TouchableOpacity>
          )}
          <TouchableOpacity onPress={onRevoke}><Text style={[styles.link, { color: Palette.danger }]}>Revoke</Text></TouchableOpacity>
        </View>
      )}
    </View>
  );
}

function RoleEditor({ member, roles, onClose, onChanged }: { member: Member; roles: Role[]; onClose: () => void; onChanged: () => void }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<number | null>(null);
  const has = (r: Role) => r.user_names.some((u) => u.id === member.id);

  const toggle = async (r: Role) => {
    setBusy(r.id);
    try {
      if (has(r)) await unassignRole(r.id, member.id); else await assignRole(r.id, member.id);
      await qc.invalidateQueries({ queryKey: ['team-roles'] });
      onChanged();
    } catch (e) {
      Alert.alert('Could not change role', errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Text style={styles.sheetTitle}>Roles for {member.username}</Text>
          <View style={styles.chips}>
            {roles.map((r) => <Chip key={r.id} label={`${busy === r.id ? '… ' : ''}${r.name}`} active={has(r)} onPress={() => busy == null && toggle(r)} />)}
          </View>
          <Text style={styles.foot}>Changes apply immediately. A company must keep at least one admin.</Text>
          <Button title="Done" variant="outline" onPress={onClose} />
        </View>
      </View>
    </Modal>
  );
}

function InviteModal({ roles, onClose, onDone }: { roles: Role[]; onClose: () => void; onDone: () => void }) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return Alert.alert('Invalid email', 'Enter a valid email address.');
    setBusy(true);
    try {
      const inv = await createInvite(email.trim(), role);
      Alert.alert(inv.mail_sent ? 'Invitation sent' : 'Invite created', inv.mail_sent ? `We emailed ${inv.email}.` : 'The email could not be delivered — use "Share link" on the invite.');
      onDone();
    } catch (e) {
      Alert.alert('Could not invite', errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <Modal transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Text style={styles.sheetTitle}>Invite someone</Text>
          <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" autoFocus />
          {roles.length > 0 && (
            <>
              <Text style={styles.label}>Role</Text>
              <View style={[styles.chips, { marginBottom: 16 }]}>
                <Chip label="Member (default)" active={role == null} onPress={() => setRole(null)} />
                {roles.map((r) => <Chip key={r.id} label={r.name} active={role === r.id} onPress={() => setRole(r.id)} />)}
              </View>
            </>
          )}
          <Button title="Send invitation" onPress={send} loading={busy} />
          <TouchableOpacity onPress={onClose} style={{ alignItems: 'center', padding: 14 }}><Text style={{ color: Palette.textMuted, fontWeight: '600' }}>Cancel</Text></TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: Palette.white, borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: Palette.border },
  cardCol: { backgroundColor: Palette.white, borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: Palette.border, gap: 3 },
  avatar: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#eef2ff', alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: Palette.primary, fontWeight: '800', fontSize: 17 },
  name: { fontSize: 15, fontWeight: '700', color: Palette.text },
  meta: { fontSize: 13, color: Palette.textMuted },
  roles: { fontSize: 13, color: Palette.primary, fontWeight: '600', marginTop: 2 },
  perms: { fontSize: 12, color: Palette.textMuted, marginTop: 4, lineHeight: 17 },
  actions: { flexDirection: 'row', gap: 20, marginTop: 8 },
  link: { color: Palette.primary, fontWeight: '700', fontSize: 14 },
  footer: { padding: 16, paddingBottom: 28, backgroundColor: Palette.white, borderTopWidth: 1, borderTopColor: Palette.border },
  foot: { fontSize: 12, color: Palette.textMuted, textAlign: 'center', marginVertical: 12 },
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.4)' },
  sheet: { backgroundColor: Palette.white, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 24, paddingBottom: 32 },
  sheetTitle: { fontSize: 18, fontWeight: '800', color: Palette.text, marginBottom: 16 },
  label: { fontSize: 14, fontWeight: '700', color: Palette.label, marginBottom: 8, marginLeft: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
