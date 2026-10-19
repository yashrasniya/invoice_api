jest.mock('@/services/api', () => ({ __esModule: true, default: {}, errorMessage: (e: unknown) => String(e) }));
jest.mock('@/services/inventory', () => ({ addMovement: jest.fn() }));
jest.mock('@/services/token-storage', () => ({ getToken: jest.fn() }));
jest.mock('expo-file-system/legacy', () => ({}));

import { invoiceBody, invoicePatchBody } from '@/services/invoices';

const TOTALS = { total: 1180, gst: 180 };

describe('invoiceBody (creating an invoice)', () => {
  it('sends the fields the form filled in', () => {
    const body = invoiceBody({
      party: 7, date: '2026-08-10', invoice_number: 'INV-1', payment_status: 'paid', payment_method: 'upi',
      due_date: '2026-08-25', place_of_supply: 27, customer_notes: 'Thanks!', terms: 'Net 15',
    }, 'sales', TOTALS);
    expect(body).toMatchObject({
      receiver: 7, invoice_type: 'sales', date: '2026-08-10', invoice_number: 'INV-1', payment_status: 'paid',
      payment_method: 'upi', due_date: '2026-08-25', place_of_supply: 27, customer_notes: 'Thanks!', terms: 'Net 15',
      total_final_amount: '1180.00', gst_final_amount: '180.00',
    });
  });

  it('omits blanks so the server can apply the company defaults', () => {
    const body = invoiceBody({
      party: 7, date: '2026-08-10', invoice_number: '  ', payment_method: null,
      due_date: null, place_of_supply: null, customer_notes: '', terms: '   ',
    }, 'sales', TOTALS);
    for (const key of ['invoice_number', 'payment_status', 'payment_method', 'due_date', 'place_of_supply', 'customer_notes', 'terms']) {
      expect(body).not.toHaveProperty(key);
    }
  });

  it('omits fields the company hides (they are never in the input)', () => {
    const body = invoiceBody({ party: 7, date: '2026-08-10' }, 'sales', TOTALS);
    expect(body).not.toHaveProperty('payment_status');
    expect(body).not.toHaveProperty('place_of_supply');
  });

  it('addresses a purchase bill to its vendor', () => {
    const body = invoiceBody({ party: 9, date: '2026-08-10' }, 'purchase', TOTALS);
    expect(body).toMatchObject({ vendor: 9, invoice_type: 'purchase' });
    expect(body).not.toHaveProperty('receiver');
  });

  it('keeps a zero place of supply out but a real state code in', () => {
    expect(invoiceBody({ party: 1, date: 'd', place_of_supply: 23 }, 'sales', TOTALS).place_of_supply).toBe(23);
  });
});

describe('invoicePatchBody (editing an invoice)', () => {
  it('sends null to clear the due date, because JSON dates reject an empty string', () => {
    expect(invoicePatchBody({ due_date: '' }, 'sales').due_date).toBeNull();
    expect(invoicePatchBody({ due_date: null }, 'sales').due_date).toBeNull();
  });

  it('keeps a real due date and clears the place of supply with null', () => {
    const body = invoicePatchBody({ due_date: '2026-08-25', place_of_supply: null }, 'sales');
    expect(body.due_date).toBe('2026-08-25');
    expect(body.place_of_supply).toBeNull();
  });

  it('leaves fields it was not given untouched', () => {
    const body = invoicePatchBody({ payment_status: 'paid' }, 'sales');
    expect(body).toEqual({ payment_status: 'paid' });
  });

  it('still blanks a cleared invoice number and maps the party', () => {
    expect(invoicePatchBody({ invoice_number: ' ', party: 4 }, 'purchase')).toMatchObject({ invoice_number: '', vendor: 4 });
  });
});
