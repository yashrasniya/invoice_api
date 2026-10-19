import React, { useMemo, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Chip, Centered } from '@/components/ui/bits';
import { LineItemModal } from '@/components/line-item-modal';
import { PartyPicker } from '@/components/party-picker';
import { StatePicker } from '@/components/state-picker';
import { Palette } from '@/constants/theme';
import { useCan, useFeature } from '@/hooks/use-access';
import { money } from '@/lib/invoice-calc';
import { defaultOf, HeaderConfig, HeaderKey, isVisible, resolveHeader } from '@/lib/header-config';
import { addDaysYmd, dueAfterDateChange, parseYmd, PAYMENT_TERMS, termDays, ymd } from '@/lib/invoice-dates';
import { summarizeLine, summarizeNewLine } from '@/lib/line-display';
import { errorMessage, isOfflineError } from '@/services/api';
import { useDrafts } from '@/store/drafts';
import { useSession } from '@/store/session';
import {
  InvoiceInput, InvoiceType, addLineItem, createInvoice, deductStock, fetchColumns, fetchHeaderConfig, Invoice, lineValues, METHOD_LABEL, NewLine, PaymentMethod, PaymentStatus,
  removeLineItem, STATUS_LABEL, syncTotals, totalsFor, updateInvoice, updateLineItem,
} from '@/services/invoices';

const STATUSES: PaymentStatus[] = ['unpaid', 'partially_paid', 'paid', 'overdue'];
const METHODS = Object.keys(METHOD_LABEL) as PaymentMethod[];

type Props = {
  invoice?: Invoice;
  /** prefill a new invoice from an existing one */
  copyFrom?: Invoice;
  /** which kind of document a new invoice is; existing ones keep their own */
  type?: InvoiceType;
};

/** Loads the company's header-field settings first, so the form starts with the right fields and defaults. */
export function InvoiceForm(props: Props) {
  const headerQ = useQuery({ queryKey: ['invoice-header-config'], queryFn: fetchHeaderConfig, staleTime: 5 * 60_000 });
  if (headerQ.isLoading) return <Centered />;
  return <InvoiceFormBody {...props} header={headerQ.data ?? resolveHeader(null)} />;
}

function InvoiceFormBody({ invoice, copyFrom, type: typeProp, header }: Props & { header: HeaderConfig }) {
  const qc = useQueryClient();
  const editing = !!invoice;
  const type: InvoiceType = invoice?.invoice_type ?? copyFrom?.invoice_type ?? typeProp ?? 'sales';
  const purchase = type === 'purchase';
  const partyKind = purchase ? 'vendor' : 'customer';
  const partyLabel = purchase ? 'Vendor' : 'Customer';
  const seed = invoice ?? copyFrom;

  const hasInventory = useFeature('inventory');
  const canManageInventory = useCan('inventory.manage');
  const canUseInventory = hasInventory && canManageInventory && !purchase;
  const columnsQ = useQuery({ queryKey: ['columns'], queryFn: fetchColumns, staleTime: 5 * 60_000 });

  const seedParty = purchase
    ? (seed?.vendor ? { id: seed.vendor, name: seed.vendor_name } : null)
    : (seed?.receiver ? { id: seed.receiver, name: seed.receiver_name } : null);
  const [customer, setCustomer] = useState<{ id: number; name: string } | null>(seedParty);
  const [date, setDate] = useState(invoice?.date ?? ymd(new Date()));
  const [number, setNumber] = useState(invoice?.invoice_number ?? '');
  // A new invoice starts from the company's defaults for the fields it shows; an existing one keeps its own values.
  const show = (key: HeaderKey) => isVisible(header, key);
  const [status, setStatus] = useState<PaymentStatus>(
    invoice?.payment_status ?? defaultOf<PaymentStatus>(header, 'payment_status') ?? 'unpaid');
  const [method, setMethod] = useState<PaymentMethod | null>(
    invoice ? invoice.payment_method : (copyFrom?.payment_method ?? defaultOf<PaymentMethod>(header, 'payment_method') ?? null));
  const [due, setDue] = useState<string | null>(() => {
    if (invoice) return invoice.due_date;
    const days = defaultOf<number>(header, 'payment_terms');
    return days === undefined ? null : addDaysYmd(ymd(new Date()), Number(days));
  });
  const [pos, setPos] = useState<number | null>(
    invoice ? invoice.place_of_supply : (copyFrom?.place_of_supply ?? defaultOf<number>(header, 'place_of_supply') ?? null));
  const [notes, setNotes] = useState(
    invoice ? invoice.customer_notes : (copyFrom?.customer_notes || defaultOf<string>(header, 'customer_notes') || ''));
  const [terms, setTerms] = useState(
    invoice ? invoice.terms : (copyFrom?.terms || defaultOf<string>(header, 'terms') || ''));
  const [showDue, setShowDue] = useState(false);
  const [newLines, setNewLines] = useState<NewLine[]>([]);
  const [removedIds, setRemovedIds] = useState<number[]>([]);
  // existing lines the user changed: productId -> new values by column id (applied on save)
  const [edited, setEdited] = useState<Record<number, Record<number, string>>>({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [pickCustomer, setPickCustomer] = useState(false);
  const [showDate, setShowDate] = useState(false);
  const [addingLine, setAddingLine] = useState(false);
  const [saving, setSaving] = useState(false);

  const columns = useMemo(() => columnsQ.data ?? [], [columnsQ.data]);

  // "Duplicate": re-create the source's lines as new lines under the current column config
  React.useEffect(() => {
    if (!copyFrom || !columnsQ.data || newLines.length) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync local form state from fetched server data / a prop change
    setNewLines(copyFrom.products.map((p) => ({
      values: Object.fromEntries(p.product_properties.map((pp) => [pp.new_product_in_frontend.id, pp.value ?? ''])),
    })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [copyFrom, columnsQ.data]);

  const keptExisting = useMemo(
    () => (invoice?.products ?? []).filter((p) => !removedIds.includes(p.id)),
    [invoice, removedIds]);
  const totals = useMemo(() => {
    const fresh = totalsFor(newLines, columns);
    const kept = keptExisting.reduce((a, p) => {
      const e = edited[p.id];
      if (e) {
        const t = totalsFor([{ values: e }], columns);
        return { total: a.total + t.total, gst: a.gst + t.gst };
      }
      return { total: a.total + Number(p.total_amount || 0), gst: a.gst + Number(p.gst_amount || 0) };
    }, { total: 0, gst: 0 });
    return { total: fresh.total + kept.total, gst: fresh.gst + kept.gst };
  }, [newLines, columns, keptExisting, edited]);

  const lineCount = newLines.length + keptExisting.length;

  // Only fields the company shows are sent. A hidden field is left out, so on a new invoice the server applies
  // the company's default for it and on an edit the stored value is untouched.
  const showPos = !purchase && show('place_of_supply');
  const buildInput = (party: number): InvoiceInput => ({
    party, date, invoice_number: number,
    ...(show('payment_status') ? { payment_status: status } : {}),
    ...(show('payment_method') ? { payment_method: method } : {}),
    ...(show('payment_terms') ? { due_date: due } : {}),
    ...(showPos ? { place_of_supply: pos } : {}),
    ...(show('customer_notes') ? { customer_notes: notes } : {}),
    ...(show('terms') ? { terms } : {}),
  });
  const changeDate = (next: string) => {
    setDue((d) => dueAfterDateChange(date, next, d));
    setDate(next);
  };
  const term = termDays(date, due);
  const posHint = pos != null
    ? "Overrides the customer's state for GST."
    : seed?.receiver_state_code
      ? `Using the customer's state (${String(seed.receiver_state_code).padStart(2, '0')}).`
      : "Defaults to the customer's state.";

  const save = async () => {
    if (!customer) return Alert.alert(`${partyLabel} required`, purchase ? 'Choose who this bill is from.' : 'Choose who this invoice is for.');
    if (lineCount === 0) return Alert.alert('No items', 'Add at least one item.');
    const party = customer;
    setSaving(true);
    try {
      let id: number;
      let warnings: string[] = [];
      if (invoice) {
        id = invoice.id;
        await updateInvoice(id, buildInput(customer.id), type);
        for (const pid of removedIds) await removeLineItem(pid);
        for (const p of keptExisting) if (edited[p.id]) await updateLineItem(p, edited[p.id], columns);
        for (const l of newLines) await addLineItem(id, l, columns);
        if (removedIds.length || newLines.length || Object.keys(edited).length) await syncTotals(id);
        warnings = await deductStock(id, newLines, columns);
      } else {
        const created = await createInvoice(buildInput(customer.id), newLines, columns, type);
        id = created.invoice.id;
        warnings = created.warnings;
      }
      await qc.invalidateQueries({ queryKey: ['invoices'] });
      await qc.invalidateQueries({ queryKey: ['invoice', id] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      router.replace(`/invoice/${id}`);
      if (warnings.length) Alert.alert('Invoice saved', warnings.join('\n'));
    } catch (e) {
      if (!editing && isOfflineError(e)) {
        // no connection: keep the work on the phone instead of losing it
        Alert.alert('You appear to be offline', 'Save this as a draft and send it when you are back online?', [
          { text: 'Keep editing', style: 'cancel' },
          { text: 'Save draft', onPress: () => {
            useDrafts.getState().add({
              owner: useSession.getState().user?.username ?? '',
              type, partyName: party.name, columns, lines: newLines,
              input: buildInput(party.id),
            });
            router.back();
            Alert.alert('Draft saved', 'Find it under More → Drafts.');
          } },
        ]);
        return;
      }
      Alert.alert(editing ? 'Could not save invoice' : 'Could not create invoice', errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  if (columnsQ.isLoading) return <Centered />;
  if (columnsQ.error || columns.length === 0) {
    return (
      <Centered>
        <Text style={styles.sectionTitle}>Invoice fields not set up</Text>
        <Text style={styles.hint}>
          {columnsQ.error ? errorMessage(columnsQ.error) : 'Your company has no item columns yet. Set them up in the web app (Invoice fields), then come back.'}
        </Text>
      </Centered>
    );
  }

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.flex}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.label}>{partyLabel}</Text>
        <TouchableOpacity style={styles.select} onPress={() => setPickCustomer(true)}>
          <Text style={[styles.selectText, !customer && { color: Palette.textFaint }]}>{customer?.name ?? `Select ${partyKind}`}</Text>
          <Ionicons name="chevron-down" size={18} color={Palette.textMuted} />
        </TouchableOpacity>

        <View style={styles.row}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Date</Text>
            <TouchableOpacity style={styles.select} onPress={() => setShowDate(true)}>
              <Text style={styles.selectText}>{date}</Text>
              <Ionicons name="calendar-outline" size={18} color={Palette.textMuted} />
            </TouchableOpacity>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>{purchase ? 'Bill no.' : 'Invoice no.'}</Text>
            <TextInput style={styles.input} value={number} onChangeText={setNumber}
              placeholder={editing || purchase ? '' : 'Auto'} placeholderTextColor={Palette.textFaint} maxLength={30} />
          </View>
        </View>
        {showDate && (
          <DateTimePicker
            value={parseYmd(date)} mode="date" display={Platform.OS === 'ios' ? 'inline' : 'default'}
            onChange={(_, d) => { if (Platform.OS !== 'ios') setShowDate(false); if (d) changeDate(ymd(d)); }}
          />
        )}
        {showDate && Platform.OS === 'ios' && (
          <Button title="Done" variant="outline" onPress={() => setShowDate(false)} style={{ height: 44, marginBottom: 12 }} />
        )}

        {show('payment_terms') && (
          <>
            <Text style={styles.label}>Payment terms</Text>
            <View style={styles.chips}>
              <Chip label="No due date" active={due === null} onPress={() => setDue(null)} />
              {PAYMENT_TERMS.map((t) => (
                <Chip key={t.days} label={t.label} active={term === t.days} onPress={() => setDue(addDaysYmd(date, t.days))} />
              ))}
            </View>
            {due !== null && (
              <>
                <Text style={styles.label}>Due date</Text>
                <TouchableOpacity style={styles.select} onPress={() => setShowDue(true)} accessibilityRole="button" accessibilityLabel="Due date">
                  <Text style={styles.selectText}>{due}</Text>
                  <Ionicons name="calendar-outline" size={18} color={Palette.textMuted} />
                </TouchableOpacity>
              </>
            )}
            {showDue && due !== null && (
              <DateTimePicker
                value={parseYmd(due)} mode="date" minimumDate={parseYmd(date)} display={Platform.OS === 'ios' ? 'inline' : 'default'}
                onChange={(_, d) => { if (Platform.OS !== 'ios') setShowDue(false); if (d) setDue(ymd(d)); }}
              />
            )}
            {showDue && due !== null && Platform.OS === 'ios' && (
              <Button title="Done" variant="outline" onPress={() => setShowDue(false)} style={{ height: 44, marginBottom: 12 }} />
            )}
          </>
        )}

        {showPos && (
          <>
            <StatePicker label="Place of supply" value={pos} onChange={setPos} />
            <Text style={styles.hint2}>{posHint}</Text>
            {pos != null && (
              <TouchableOpacity onPress={() => setPos(null)} accessibilityRole="button" hitSlop={8}>
                <Text style={styles.link}>Use the customer&apos;s state</Text>
              </TouchableOpacity>
            )}
          </>
        )}

        {show('payment_status') && (
          <>
            <Text style={styles.label}>Payment status</Text>
            <View style={styles.chips}>
              {STATUSES.map((s) => <Chip key={s} label={STATUS_LABEL[s]} active={status === s} onPress={() => setStatus(s)} />)}
            </View>
          </>
        )}

        {show('payment_method') && (
          <>
            <Text style={styles.label}>Payment method</Text>
            <View style={styles.chips}>
              {METHODS.map((m) => <Chip key={m} label={METHOD_LABEL[m]} active={method === m} onPress={() => setMethod(method === m ? null : m)} />)}
            </View>
          </>
        )}

        <Text style={[styles.sectionTitle, { marginTop: 24 }]}>Items</Text>
        {keptExisting.map((p) => {
          const e = edited[p.id];
          const sm = e ? summarizeNewLine({ values: e }, columns) : summarizeLine(p);
          const amount = e ? totalsFor([{ values: e }], columns).total : Number(p.total_amount || 0);
          return (
            <View key={`e${p.id}`} style={styles.line}>
              <TouchableOpacity style={{ flex: 1 }} onPress={() => setEditingId(p.id)} accessibilityRole="button" accessibilityLabel={`Edit item ${sm.name}`}>
                <Text style={styles.lineName}>{sm.name}{e ? '  ·  edited' : ''}</Text>
                {!!sm.details && <Text style={styles.lineSub}>{sm.details}</Text>}
              </TouchableOpacity>
              <Text style={styles.lineAmt}>{money(amount)}</Text>
              <TouchableOpacity hitSlop={10} onPress={() => setEditingId(p.id)} accessibilityLabel="Edit item">
                <Ionicons name="create-outline" size={20} color={Palette.primary} />
              </TouchableOpacity>
              <TouchableOpacity hitSlop={10} onPress={() => setRemovedIds((r) => [...r, p.id])} accessibilityLabel="Remove item">
                <Ionicons name="trash-outline" size={20} color={Palette.danger} />
              </TouchableOpacity>
            </View>
          );
        })}
        {newLines.map((l, i) => {
          const s = summarizeNewLine(l, columns);
          const t = totalsFor([l], columns).total;
          return (
            <View key={`n${i}`} style={styles.line}>
              <View style={{ flex: 1 }}>
                <Text style={styles.lineName}>{s.name}</Text>
                {!!s.details && <Text style={styles.lineSub}>{s.details}</Text>}
              </View>
              <Text style={styles.lineAmt}>{money(t)}</Text>
              <TouchableOpacity hitSlop={10} onPress={() => setNewLines((x) => x.filter((_, j) => j !== i))}>
                <Ionicons name="trash-outline" size={20} color={Palette.danger} />
              </TouchableOpacity>
            </View>
          );
        })}
        <TouchableOpacity style={styles.addLine} onPress={() => setAddingLine(true)}>
          <Ionicons name="add-circle-outline" size={22} color={Palette.primary} />
          <Text style={styles.addLineText}>Add item</Text>
        </TouchableOpacity>

        {show('customer_notes') && (
          <>
            <Text style={styles.label}>Notes</Text>
            <TextInput style={[styles.input, styles.textarea]} value={notes} onChangeText={setNotes} multiline maxLength={2000}
              placeholder="Thanks for your business" placeholderTextColor={Palette.textFaint} accessibilityLabel="Notes" />
          </>
        )}
        {show('terms') && (
          <>
            <Text style={styles.label}>Terms and conditions</Text>
            <TextInput style={[styles.input, styles.textarea]} value={terms} onChangeText={setTerms} multiline maxLength={2000}
              placeholder="Payment due within the terms above" placeholderTextColor={Palette.textFaint} accessibilityLabel="Terms and conditions" />
          </>
        )}
      </ScrollView>

      <View style={styles.footer}>
        <View style={{ flex: 1 }}>
          <Text style={styles.footLabel}>GST {money(totals.gst)}</Text>
          <Text style={styles.footTotal}>{money(totals.total)}</Text>
        </View>
        <Button title={editing ? 'Save changes' : purchase ? 'Save bill' : 'Create invoice'} onPress={save} loading={saving} style={{ width: 180 }} />
      </View>

      <PartyPicker kind={partyKind} visible={pickCustomer} onClose={() => setPickCustomer(false)}
        onPick={(p) => setCustomer({ id: p.id, name: p.name })} />
      {editingId != null && (() => {
        const line = (invoice?.products ?? []).find((p) => p.id === editingId);
        return line ? (
          <LineItemModal
            visible columns={columns} title="Edit item" saveLabel="Save item"
            initialValues={edited[line.id] ?? lineValues(line)}
            onClose={() => setEditingId(null)}
            onSave={(l) => { setEdited((x) => ({ ...x, [line.id]: l.values })); setEditingId(null); }}
          />
        ) : null;
      })()}
      <LineItemModal visible={addingLine} columns={columns} useInventory={canUseInventory} onClose={() => setAddingLine(false)}
        onSave={(l) => { setNewLines((x) => [...x, l]); setAddingLine(false); }} />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: Palette.white },
  scroll: { padding: 20, paddingBottom: 40 },
  label: { fontSize: 14, fontWeight: '700', color: Palette.label, marginBottom: 6, marginTop: 14 },
  row: { flexDirection: 'row', gap: 12 },
  select: { height: 50, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1.5, borderColor: Palette.border, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  selectText: { fontSize: 16, color: Palette.text, flexShrink: 1 },
  input: { height: 50, borderRadius: 12, backgroundColor: Palette.surface, borderWidth: 1.5, borderColor: Palette.border, paddingHorizontal: 14, fontSize: 16, color: Palette.text },
  textarea: { height: undefined, minHeight: 84, paddingTop: 12, textAlignVertical: 'top' },
  hint2: { fontSize: 12, color: Palette.textMuted, marginTop: 6 },
  link: { fontSize: 13, fontWeight: '700', color: Palette.primary, marginTop: 6 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  sectionTitle: { fontSize: 18, fontWeight: '800', color: Palette.text },
  hint: { color: Palette.textMuted, textAlign: 'center', marginTop: 8, lineHeight: 20 },
  line: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: Palette.border },
  lineName: { fontSize: 16, fontWeight: '600', color: Palette.text },
  lineSub: { fontSize: 12, color: Palette.textMuted, marginTop: 2 },
  lineAmt: { fontSize: 15, fontWeight: '700', color: Palette.text },
  addLine: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 16 },
  addLineText: { color: Palette.primary, fontWeight: '700', fontSize: 16 },
  footer: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 16, paddingBottom: 28, borderTopWidth: 1, borderTopColor: Palette.border, backgroundColor: Palette.white },
  footLabel: { fontSize: 12, color: Palette.textMuted },
  footTotal: { fontSize: 22, fontWeight: '800', color: Palette.text },
});
