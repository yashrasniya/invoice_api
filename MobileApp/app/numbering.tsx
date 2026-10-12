import React, { useEffect, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Section } from '@/components/report-ui';
import { Button } from '@/components/ui/button';
import { Centered, Chip, EmptyState } from '@/components/ui/bits';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { useCan } from '@/hooks/use-access';
import { errorMessage } from '@/services/api';
import { fetchNumbering, NumberingPreview, previewNumbering, saveNumbering } from '@/services/templates';

export default function NumberingScreen() {
  const qc = useQueryClient();
  const canEdit = useCan('template.manage');
  const q = useQuery({ queryKey: ['numbering'], queryFn: fetchNumbering });
  const [enabled, setEnabled] = useState(false);
  const [template, setTemplate] = useState('');
  const [reset, setReset] = useState('never');
  const [next, setNext] = useState('1');
  const [preview, setPreview] = useState<NumberingPreview | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const d = q.data;
    if (!d) return;
    setEnabled(d.enabled); setTemplate(d.template); setReset(d.reset_period); setNext(String(d.next_number));
  }, [q.data]);

  // live preview while editing (the endpoint answers 200 with valid:false for half-typed templates)
  useEffect(() => {
    if (!q.data) return;
    const t = setTimeout(() => {
      previewNumbering(template, reset, Math.max(1, Number(next) || 1)).then(setPreview).catch(() => setPreview(null));
    }, 400);
    return () => clearTimeout(t);
  }, [template, reset, next, q.data]);

  const save = async () => {
    const n = Number(next);
    if (!Number.isInteger(n) || n < 1) return Alert.alert('Invalid number', 'Next number must be a whole number of at least 1.');
    setSaving(true);
    try {
      await saveNumbering({ enabled, template: template.trim(), reset_period: reset, next_number: n });
      await qc.invalidateQueries({ queryKey: ['numbering'] });
      Alert.alert('Saved', 'Invoice numbering updated.');
    } catch (e) {
      Alert.alert('Could not save', errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  if (q.isLoading) return <Centered />;
  if (q.error || !q.data) return <><Stack.Screen options={{ title: 'Invoice numbering' }} /><EmptyState icon="alert-circle-outline" title="Couldn't load numbering" hint={errorMessage(q.error)} /></>;
  const d = q.data;

  return (
    <>
      <Stack.Screen options={{ title: 'Invoice numbering' }} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView style={styles.screen} contentContainerStyle={{ padding: 16, paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
          <Section title="Automatic numbering">
            <View style={styles.rowBetween}>
              <Text style={styles.label}>Number new invoices automatically</Text>
              <Switch value={enabled} onValueChange={setEnabled} disabled={!canEdit} trackColor={{ true: Palette.primary }} />
            </View>
          </Section>

          <Section title="Format">
            <Field label="Template" value={template} onChangeText={setTemplate} editable={canEdit} autoCapitalize="characters" maxLength={60} />
            {canEdit && (
              <View style={styles.chips}>
                {d.tokens.map((t) => <Chip key={t.token} label={t.token} onPress={() => setTemplate((s) => s + t.token)} />)}
              </View>
            )}
            <View style={styles.previewBox}>
              <Text style={styles.previewLabel}>Preview</Text>
              {preview?.valid ? (
                <>
                  <Text style={styles.previewValue}>{preview.preview}</Text>
                  {preview.gst_warning && <Text style={styles.warn}>Longer than the 16 characters GST recommends.</Text>}
                </>
              ) : <Text style={styles.warn}>{preview?.error ?? '—'}</Text>}
            </View>
          </Section>

          <Section title="Counter">
            <Text style={styles.label}>Restart the counter</Text>
            <View style={[styles.chips, { marginVertical: 8 }]}>
              {d.reset_options.map((o) => <Chip key={o.value} label={o.label} active={reset === o.value} onPress={() => canEdit && setReset(o.value)} />)}
            </View>
            <Field label="Next number" value={next} onChangeText={setNext} keyboardType="number-pad" editable={canEdit} />
          </Section>

          {canEdit ? <Button title="Save" onPress={save} loading={saving} /> : <Text style={styles.note}>Only admins can change numbering.</Text>}
          <Text style={styles.note}>Typing your own invoice number on an invoice always overrides this.</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  label: { fontSize: 14, fontWeight: '600', color: Palette.text, flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  previewBox: { marginTop: 14, padding: 14, borderRadius: 12, backgroundColor: Palette.surface },
  previewLabel: { fontSize: 12, color: Palette.textMuted, fontWeight: '600' },
  previewValue: { fontSize: 22, fontWeight: '800', color: Palette.primary, marginTop: 2 },
  warn: { fontSize: 13, color: Palette.danger, marginTop: 4 },
  note: { fontSize: 12, color: Palette.textMuted, textAlign: 'center', marginTop: 14 },
});
