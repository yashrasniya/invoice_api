import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Section } from '@/components/report-ui';
import { useTheme, useThemedStyles, type Theme } from '@/hooks/use-theme';
import { money } from '@/lib/invoice-calc';
import type { Gstr1Issue, TaxRow } from '@/services/reports';

/** "IGST ₹x · CGST ₹y · SGST ₹z", leaving out heads that are zero. */
export function headsText(r: Pick<TaxRow, 'igst' | 'cgst' | 'sgst'>) {
  const parts = [['IGST', r.igst], ['CGST', r.cgst], ['SGST', r.sgst]]
    .filter(([, v]) => Number(v) !== 0).map(([h, v]) => `${h} ${money(v as number)}`);
  return parts.length ? parts.join(' · ') : 'No tax';
}

/** One row of a return table: label + code, taxable value, tax by head. */
export function TaxLine({ row, showTaxable = true, bold }: { row: TaxRow & { key?: string; label?: string }; showTaxable?: boolean; bold?: boolean }) {
  const styles = useThemedStyles(makeStyles);
  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text style={[styles.label, bold && styles.bold]}>{row.key ? `${row.key} · ` : ''}{row.label}</Text>
        <Text style={styles.sub}>{headsText(row)}</Text>
      </View>
      {showTaxable && <Text style={[styles.value, bold && styles.bold]}>{money(row.taxable)}</Text>}
    </View>
  );
}

/** One thing to fix. Tapping an invoice issue opens that invoice. */
function IssueRow({ issue }: { issue: Gstr1Issue }) {
  const theme = useTheme();
  const styles = useThemedStyles(makeStyles);
  const tone = issue.level === 'error' ? theme.danger : theme.warning;
  const ref = issue.ref;
  const open = ref?.kind === 'invoice' ? () => router.push(`/invoice/${ref.id}`) : undefined;
  return (
    <TouchableOpacity style={styles.issue} onPress={open} disabled={!open} accessibilityRole={open ? 'button' : undefined}>
      <Ionicons name={issue.level === 'error' ? 'close-circle' : 'alert-circle'} size={18} color={tone} />
      <View style={{ flex: 1 }}>
        {!!ref && (
          <Text style={styles.issueRef}>
            {ref.kind === 'note' ? 'Note' : 'Invoice'} {ref.number || `#${ref.id}`}{ref.date ? ` · ${ref.date}` : ''}
          </Text>
        )}
        <Text style={styles.issueText}>{issue.message}</Text>
      </View>
      {!!open && <Ionicons name="chevron-forward" size={16} color={theme.textFaint} />}
    </TouchableOpacity>
  );
}

/** Errors then warnings, each in its own section; nothing when there are none. */
export function IssueSections({ issues }: { issues: Gstr1Issue[] }) {
  const errors = issues.filter((i) => i.level === 'error');
  const warnings = issues.filter((i) => i.level !== 'error');
  return (
    <>
      {errors.length > 0 && (
        <Section title={`Fix first (${errors.length})`}>
          {errors.map((i, n) => <IssueRow key={`e${n}`} issue={i} />)}
        </Section>
      )}
      {warnings.length > 0 && (
        <Section title={`Review (${warnings.length})`}>
          {warnings.map((i, n) => <IssueRow key={`w${n}`} issue={i} />)}
        </Section>
      )}
    </>
  );
}

const makeStyles = (t: Theme) => StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border },
  label: { fontSize: 14, color: t.text },
  sub: { fontSize: 12, color: t.textMuted, marginTop: 2 },
  value: { fontSize: 14, color: t.text, fontWeight: '600', fontVariant: ['tabular-nums'], textAlign: 'right' },
  bold: { fontWeight: '800' },
  issue: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.border },
  issueRef: { fontSize: 12, fontWeight: '700', color: t.textMuted, marginBottom: 2 },
  issueText: { fontSize: 13, color: t.text, lineHeight: 18 },
});
