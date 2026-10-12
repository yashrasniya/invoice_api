import React, { useState } from 'react';
import { Alert, FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Image } from 'expo-image';
import { Stack } from 'expo-router';
import * as Sharing from 'expo-sharing';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PeriodBar } from '@/components/report-ui';
import { Centered, Chip, EmptyState } from '@/components/ui/bits';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';
import { errorMessage } from '@/services/api';
import { cloneTemplate, downloadPreview, fetchGallery, fetchMyTemplates, GalleryTemplate, setDefaultTemplate } from '@/services/templates';

export default function TemplatesScreen() {
  const qc = useQueryClient();
  const hasDesigner = useFeature('template_designer');
  const canManage = useCan('template.manage');
  const canChange = hasDesigner && canManage;
  const [tab, setTab] = useState<'mine' | 'gallery'>('mine');
  const [category, setCategory] = useState('');
  const [busy, setBusy] = useState<number | null>(null);

  const mine = useQuery({ queryKey: ['my-templates'], queryFn: fetchMyTemplates });
  const gallery = useQuery({ queryKey: ['gallery'], queryFn: () => fetchGallery(), enabled: tab === 'gallery' });
  const categories = Array.from(new Set((gallery.data ?? []).map((t) => t.global_category).filter(Boolean)));
  const shown = (gallery.data ?? []).filter((t) => !category || t.global_category === category);

  const makeDefault = useMutation({
    mutationFn: setDefaultTemplate,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['my-templates'] }); qc.invalidateQueries({ queryKey: ['wa-mode'] }); },
    onError: (e) => Alert.alert('Could not set default', errorMessage(e)),
  });

  const preview = async (t: GalleryTemplate) => {
    setBusy(t.id);
    try {
      const uri = await downloadPreview(t.id);
      if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(uri, { mimeType: 'application/pdf', dialogTitle: t.template_name, UTI: 'com.adobe.pdf' });
    } catch (e) {
      Alert.alert('No preview', errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const clone = (t: GalleryTemplate) =>
    Alert.alert('Add template', `Add "${t.template_name}" to your templates?`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Add', onPress: async () => {
        setBusy(t.id);
        try { await cloneTemplate(t.id); await qc.invalidateQueries({ queryKey: ['my-templates'] }); Alert.alert('Added', 'It is now in My templates.'); setTab('mine'); }
        catch (e) { Alert.alert('Could not add', errorMessage(e)); }
        finally { setBusy(null); }
      } },
    ]);

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: 'Invoice templates' }} />
      <PeriodBar options={[{ value: 'mine', label: 'My templates' }, { value: 'gallery', label: 'Gallery' }]} value={tab} onChange={setTab} />

      {tab === 'mine' ? (mine.isLoading ? <Centered /> : (
        <FlatList data={mine.data ?? []} keyExtractor={(t) => String(t.id)} contentContainerStyle={{ padding: 16, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={mine.isRefetching} onRefresh={() => { void mine.refetch(); }} />}
          ListEmptyComponent={<EmptyState icon="document-outline" title="No templates" hint={errorMessage(mine.error, 'Browse the gallery to add one.')} />}
          ListFooterComponent={<Text style={styles.foot}>Editing template layouts is available on the web.</Text>}
          renderItem={({ item }) => (
            <View style={styles.card}>
              {item.pdf_template ? <Image source={{ uri: item.pdf_template }} style={styles.thumb} contentFit="cover" /> : <View style={[styles.thumb, styles.noThumb]} />}
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.name} numberOfLines={2}>{item.template_name}</Text>
                {item.is_default ? <Text style={styles.badge}>Default</Text> : canChange ? (
                  <TouchableOpacity onPress={() => makeDefault.mutate(item.id)}><Text style={styles.link}>Set as default</Text></TouchableOpacity>
                ) : null}
              </View>
            </View>
          )} />
      )) : (gallery.isLoading ? <Centered /> : (
        <>
          {categories.length > 0 && (
            <View style={styles.cats}>
              <Chip label="All" active={!category} onPress={() => setCategory('')} />
              {categories.map((c) => <Chip key={c} label={c} active={category === c} onPress={() => setCategory(c)} />)}
            </View>
          )}
          <FlatList data={shown} keyExtractor={(t) => String(t.id)} contentContainerStyle={{ padding: 16, flexGrow: 1 }}
            refreshControl={<RefreshControl refreshing={gallery.isRefetching} onRefresh={() => { void gallery.refetch(); }} />}
            ListEmptyComponent={<EmptyState icon="images-outline" title="Nothing here" hint={errorMessage(gallery.error, '')} />}
            renderItem={({ item }) => (
              <View style={styles.card}>
                {item.pdf_template ? <Image source={{ uri: item.pdf_template }} style={styles.thumb} contentFit="cover" /> : <View style={[styles.thumb, styles.noThumb]} />}
                <View style={{ flex: 1, gap: 4 }}>
                  <Text style={styles.name} numberOfLines={2}>{item.template_name}</Text>
                  {!!item.global_category && <Text style={styles.meta}>{item.global_category}</Text>}
                  <View style={styles.actions}>
                    {item.preview_url && <TouchableOpacity disabled={busy === item.id} onPress={() => preview(item)}><Text style={styles.link}>{busy === item.id ? 'Working…' : 'Preview PDF'}</Text></TouchableOpacity>}
                    {canChange && <TouchableOpacity disabled={busy === item.id} onPress={() => clone(item)}><Text style={styles.link}>Use this</Text></TouchableOpacity>}
                  </View>
                </View>
              </View>
            )}
            ListFooterComponent={!canChange ? <Text style={styles.foot}>{hasDesigner ? "You don't have permission to add templates." : 'Adding templates needs a plan with the template designer.'}</Text> : undefined} />
        </>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.surface },
  cats: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingHorizontal: 16, paddingTop: 12 },
  card: { flexDirection: 'row', gap: 14, backgroundColor: Palette.white, borderRadius: 14, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: Palette.border },
  thumb: { width: 84, height: 112, borderRadius: 8, backgroundColor: Palette.surface },
  noThumb: { borderWidth: 1, borderColor: Palette.border },
  name: { fontSize: 15, fontWeight: '700', color: Palette.text },
  meta: { fontSize: 12, color: Palette.textMuted },
  badge: { alignSelf: 'flex-start', backgroundColor: '#dcfce7', color: '#166534', fontSize: 12, fontWeight: '700', paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, overflow: 'hidden' },
  actions: { flexDirection: 'row', gap: 18, marginTop: 6 },
  link: { color: Palette.primary, fontWeight: '700', fontSize: 14 },
  foot: { fontSize: 12, color: Palette.textMuted, textAlign: 'center', marginVertical: 12 },
});
