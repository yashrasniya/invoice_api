import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Palette } from '@/constants/theme';
import { compactInr } from '@/lib/invoice-calc';

export type Group = { label: string; values: number[] };

/**
 * Plain-View bar chart (no chart dependency): grouped bars, scrolls sideways when
 * there are many groups. Negative values are drawn as zero-height — callers that
 * care about sign (cash flow net) show it as text instead.
 */
export function BarChart({ data, colors = [Palette.primary], height = 140, barWidth = 14 }: {
  data: Group[]; colors?: string[]; height?: number; barWidth?: number;
}) {
  const max = Math.max(1, ...data.flatMap((g) => g.values.map((v) => Math.max(0, v))));
  const every = Math.max(1, Math.ceil(data.length / 6));
  const groupWidth = barWidth * colors.length + 10;

  return (
    <View>
      <Text style={styles.axis}>{compactInr(max)}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={[styles.plot, { height: height + 22 }]}>
          {data.map((g, i) => (
            <View key={`${g.label}-${i}`} style={{ width: groupWidth, alignItems: 'center' }}>
              <View style={{ height, flexDirection: 'row', alignItems: 'flex-end', gap: 2 }}>
                {g.values.map((v, j) => (
                  <View key={j} style={{ width: barWidth, height: Math.max(v > 0 ? 2 : 0, (Math.max(0, v) / max) * height), backgroundColor: colors[j % colors.length], borderTopLeftRadius: 3, borderTopRightRadius: 3 }} />
                ))}
              </View>
              <Text style={styles.tick} numberOfLines={1}>{i % every === 0 ? g.label : ' '}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

export function HBarList({ items, color = Palette.primary }: { items: { label: string; value: number }[]; color?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <View style={{ gap: 10 }}>
      {items.map((it) => (
        <View key={it.label}>
          <View style={styles.hRow}>
            <Text style={styles.hLabel} numberOfLines={1}>{it.label}</Text>
            <Text style={styles.hValue}>{compactInr(it.value)}</Text>
          </View>
          <View style={styles.track}>
            <View style={[styles.fill, { width: `${Math.max(2, (it.value / max) * 100)}%`, backgroundColor: color }]} />
          </View>
        </View>
      ))}
    </View>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <View style={styles.legend}>
      {items.map((i) => (
        <View key={i.label} style={styles.legendItem}>
          <View style={[styles.dot, { backgroundColor: i.color }]} />
          <Text style={styles.legendText}>{i.label}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  axis: { fontSize: 11, color: Palette.textMuted, marginBottom: 4 },
  plot: { flexDirection: 'row', alignItems: 'flex-end', borderBottomWidth: 1, borderBottomColor: Palette.border },
  tick: { fontSize: 10, color: Palette.textMuted, marginTop: 4, height: 14 },
  hRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 },
  hLabel: { fontSize: 14, color: Palette.text, flex: 1, marginRight: 8 },
  hValue: { fontSize: 14, fontWeight: '700', color: Palette.text },
  track: { height: 8, borderRadius: 4, backgroundColor: Palette.border, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4 },
  legend: { flexDirection: 'row', gap: 16, marginTop: 10 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontSize: 12, color: Palette.textMuted },
});
