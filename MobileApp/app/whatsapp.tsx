import React, { useState } from 'react';
import { Alert, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Stack } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Section } from '@/components/report-ui';
import { Button } from '@/components/ui/button';
import { Centered, Chip, EmptyState } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';
import { errorMessage, WEB_URL } from '@/services/api';
import { fetchMyTemplates } from '@/services/templates';
import {
  fetchWaConfig, fetchWaMode, fetchWaTemplates, sendWaTest, syncWaTemplates, updateWaMode, WaMode,
} from '@/services/whatsapp';

const MODE_LABEL: Record<WaMode, string> = { platform: 'Shared number', own: 'My own number' };

export default function WhatsAppScreen() {
  const qc = useQueryClient();
  const canManage = useCan('whatsapp.manage');
  const canSend = useCan('whatsapp.send');
  const hasOwn = useFeature('whatsapp_integration');
  const [recipient, setRecipient] = useState('');
  const [tplName, setTplName] = useState('');

  const mode = useQuery({ queryKey: ['wa-mode'], queryFn: fetchWaMode });
  const config = useQuery({ queryKey: ['wa-config'], queryFn: fetchWaConfig, enabled: hasOwn });
  const templates = useQuery({ queryKey: ['wa-templates'], queryFn: fetchWaTemplates, enabled: hasOwn });
  const invoiceTemplates = useQuery({ queryKey: ['my-templates'], queryFn: fetchMyTemplates });

  const refresh = () => qc.invalidateQueries({ queryKey: ['wa-mode'] });
  const update = useMutation({
    mutationFn: updateWaMode,
    onSuccess: refresh,
    onError: (e) => Alert.alert('Could not update', errorMessage(e)),
  });
  const sync = useMutation({
    mutationFn: syncWaTemplates,
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['wa-templates'] }); Alert.alert('Synced', `${r.added} new, ${r.updated} updated.`); },
    onError: (e) => Alert.alert('Sync failed', errorMessage(e)),
  });
  const test = useMutation({
    mutationFn: () => sendWaTest(recipient.trim(), tplName.trim()),
    onSuccess: () => Alert.alert('Sent', 'Test message sent.'),
    onError: (e) => Alert.alert('Could not send', errorMessage(e)),
  });

  if (mode.isLoading) return <Centered />;
  if (mode.error || !mode.data) {
    return <><Stack.Screen options={{ title: 'WhatsApp' }} /><EmptyState icon="alert-circle-outline" title="Couldn't load WhatsApp settings" hint={errorMessage(mode.error)} /></>;
  }
  const m = mode.data;
  const ownConnected = config.data?.status === 'active';
  const openWeb = () => WEB_URL && WebBrowser.openBrowserAsync(`${WEB_URL}/whatsapp-settings`);

  return (
    <>
      <Stack.Screen options={{ title: 'WhatsApp' }} />
      <ScrollView style={styles.screen} contentContainerStyle={{ padding: 16 }}
        refreshControl={<RefreshControl refreshing={mode.isRefetching} onRefresh={() => { mode.refetch(); config.refetch(); templates.refetch(); }} />}>

        <Section title="Sending number">
          {(['platform', 'own'] as WaMode[]).map((k) => {
            const o = m.options[k];
            const active = m.mode === k;
            const note = !o.in_plan ? 'Not in your plan' : k === 'own' && !o.configured ? 'Not connected yet' : k === 'platform' && !o.configured ? 'Unavailable right now' : o.sends_per_day != null ? `${o.sends_per_day} sends per day` : '';
            return (
              <TouchableOpacity key={k} disabled={!canManage || active || !o.available || update.isPending}
                style={[styles.option, active && styles.optionActive, !o.available && { opacity: 0.55 }]}
                onPress={() => update.mutate({ mode: k })}>
                <View style={[styles.radio, active && styles.radioActive]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.optionTitle}>{MODE_LABEL[k]}</Text>
                  {!!note && <Text style={styles.optionNote}>{note}</Text>}
                </View>
              </TouchableOpacity>
            );
          })}
          {!canManage && <Text style={styles.note}>Only admins can change this.</Text>}
        </Section>

        <Section title="Invoice template for WhatsApp">
          <Text style={styles.note}>Used when you send an invoice without choosing a template.</Text>
          <View style={styles.chips}>
            <Chip label="Company default" active={!m.default_invoice_template} onPress={() => canManage && update.mutate({ default_invoice_template: null })} />
            {(invoiceTemplates.data ?? []).map((t) => (
              <Chip key={t.id} label={t.template_name} active={m.default_invoice_template?.id === t.id}
                onPress={() => canManage && update.mutate({ default_invoice_template: t.id })} />
            ))}
          </View>
        </Section>

        {hasOwn ? (
          <>
            <Section title="Your WhatsApp Business number">
              <Text style={styles.status}>
                {ownConnected ? '● Connected' : config.data?.status === 'not_configured' || !config.data ? '○ Not connected' : `● ${config.data.status}`}
              </Text>
              {!ownConnected && (
                <>
                  <Text style={styles.note}>Connecting a business number needs Meta sign-in, so it is done on the web.</Text>
                  <Button title="Connect on the web" variant="outline" onPress={openWeb} style={{ height: 46, marginTop: 8 }} />
                </>
              )}
            </Section>

            {ownConnected && (
              <>
                <Section title="Message templates">
                  {(templates.data ?? []).length === 0 && <Text style={styles.note}>No templates yet.</Text>}
                  {(templates.data ?? []).map((t) => (
                    <TouchableOpacity key={t.id} style={styles.tpl} onPress={() => setTplName(t.template_name)}>
                      <Text style={styles.tplName}>{t.template_name}</Text>
                      <Text style={styles.tplMeta}>{t.category} · {t.status}</Text>
                    </TouchableOpacity>
                  ))}
                  {canManage && <Button title="Sync from Meta" variant="outline" onPress={() => sync.mutate()} loading={sync.isPending} style={{ height: 46, marginTop: 8 }} />}
                </Section>

                {canSend && (
                  <Section title="Send a test message">
                    <Field label="Recipient number" placeholder="919876543210" value={recipient} onChangeText={setRecipient} keyboardType="phone-pad" />
                    <Field label="Template name" value={tplName} onChangeText={setTplName} autoCapitalize="none" />
                    <Button title="Send test" onPress={() => (!recipient.trim() || !tplName.trim() ? Alert.alert('Missing details', 'Enter a number and template name.') : test.mutate())} loading={test.isPending} />
                  </Section>
                )}
              </>
            )}
          </>
        ) : (
          <Text style={styles.note}>Using your own WhatsApp number is not part of your plan.</Text>
        )}
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  option: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 12, borderWidth: 1.5, borderColor: Palette.border, marginBottom: 8 },
  optionActive: { borderColor: Palette.primary, backgroundColor: '#eef2ff' },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: Palette.textFaint },
  radioActive: { borderColor: Palette.primary, backgroundColor: Palette.primary },
  optionTitle: { fontSize: 15, fontWeight: '700', color: Palette.text },
  optionNote: { fontSize: 12, color: Palette.textMuted, marginTop: 2 },
  note: { fontSize: 13, color: Palette.textMuted, marginBottom: 8, lineHeight: 18 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  status: { fontSize: 16, fontWeight: '700', color: Palette.text, marginBottom: 6 },
  tpl: { paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: Palette.border },
  tplName: { fontSize: 14, fontWeight: '600', color: Palette.text },
  tplMeta: { fontSize: 12, color: Palette.textMuted, marginTop: 2 },
});
