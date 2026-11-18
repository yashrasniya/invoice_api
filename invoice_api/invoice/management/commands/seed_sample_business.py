"""
Fill an account with a year of realistic trading data for manual testing.

    python manage.py seed_sample_business --user aarti --fix-company
    python manage.py seed_sample_business --user aarti --wipe

Unlike `seed_demo_data`, nothing visible is tagged: names, numbers, SKUs and
notes all look like a real hardware & electricals trader's books. Every row
created is instead recorded in a manifest file (see `manifest_path`), and
`--wipe` deletes exactly those rows.

Contact details are deliberately *not* random. This app sends invoices on
WhatsApp and by email, and a random 10-digit number or address could belong
to a real person. Every customer and vendor gets the acting user's own
mobile number and a plus-address of the user's own email
(`name+zenith@gmail.com`), so anything sent while testing reaches only you.

What it covers, so each screen has something to show:
  * customers across GST treatments: registered (intra- and inter-state),
    unregistered, consumer (B2C), SEZ and overseas
  * vendors, purchase bills (incl. reverse-charge freight)
  * ~12 months of sales invoices through the company's numbering series,
    with HSN, unit, GST rate per line; totals via the server's line_calc
  * payments (full and part), overdue and unpaid invoices
  * credit and debit notes with GST
  * inventory: categories, suppliers, items with HSN/unit, opening stock,
    stock-out movements for invoiced lines, some items at reorder level
"""
import json
import random
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.gst_utils import gstin_check_char
from accounts.models import User, UserCompanies
from companies.models import Customers, Vendor
from inventory.models import Category, Product as StockItem, StockMovement, Supplier
from invoice.line_calc import recompute_invoice_totals, recompute_product
from invoice.models import (CreditDebitNote, Invoice, Payment, Product,
                            Product_properties, new_product_in_frontend)
from invoice.numbering import next_invoice_number

STATE_NAMES = {
    27: 'Maharashtra', 24: 'Gujarat', 29: 'Karnataka', 7: 'Delhi', 33: 'Tamil Nadu',
    9: 'Uttar Pradesh', 8: 'Rajasthan', 36: 'Telangana', 30: 'Goa', 23: 'Madhya Pradesh',
    5: 'Uttarakhand', 6: 'Haryana',
}

# (name, legal name, city, state code, treatment, business type)
CUSTOMERS = [
    ('Zenith Traders', 'Zenith Traders', 'Mumbai', 27, 'registered', 'partnership'),
    ('Patel & Sons Hardware', 'Patel and Sons', 'Thane', 27, 'registered', 'partnership'),
    ('Shree Ganesh Constructions', 'Shree Ganesh Constructions Pvt Ltd', 'Pune', 27, 'registered', 'private_limited'),
    ('Kamal Electricals', 'Kamal Electricals', 'Nashik', 27, 'registered', 'sole_prop'),
    ('Sai Krupa Interiors', 'Sai Krupa Interiors LLP', 'Navi Mumbai', 27, 'registered', 'llp'),
    ('Meridian Builders', 'Meridian Builders Pvt Ltd', 'Ahmedabad', 24, 'registered', 'private_limited'),
    ('Deccan Infra Projects', 'Deccan Infra Projects Pvt Ltd', 'Bengaluru', 29, 'registered', 'private_limited'),
    ('Goa Coastal Resorts', 'Goa Coastal Resorts Pvt Ltd', 'Panaji', 30, 'registered', 'private_limited'),
    ('Sharma Hardware Mart', 'Sharma Hardware Mart', 'Indore', 23, 'composition', 'sole_prop'),
    ('Rohan Desai', '', 'Mumbai', 27, 'consumer', 'other'),
    ('Neha Kulkarni', '', 'Mumbai', 27, 'consumer', 'other'),
    ('Om Sai Repairs', 'Om Sai Repairs', 'Kalyan', 27, 'unregistered', 'sole_prop'),
    ('Seepz Electronics Unit 4', 'Seepz Precision Electronics Pvt Ltd', 'Mumbai', 27, 'sez', 'private_limited'),
    ('Al Noor Building Supplies', 'Al Noor Building Supplies LLC', 'Dubai', 96, 'overseas', 'other'),
]

# (name, legal name, city, state code, treatment)
VENDORS = [
    ('Apex Steel Distributors', 'Apex Steel Distributors Pvt Ltd', 'Mumbai', 27, 'registered'),
    ('Sundar Paints & Chemicals', 'Sundar Paints and Chemicals', 'Vapi', 24, 'registered'),
    ('Bharat Cables Ltd', 'Bharat Cables Limited', 'Daman', 24, 'registered'),
    ('Trident Ply House', 'Trident Ply House', 'Bhiwandi', 27, 'registered'),
    ('Orion Lighting Co', 'Orion Lighting Company', 'New Delhi', 7, 'registered'),
    ('Iyer Roadways', '', 'Mumbai', 27, 'unregistered'),   # freight under reverse charge
]

CATEGORIES = {
    'Plumbing': 'Pipes, fittings and accessories',
    'Electricals': 'Wires, switches, lighting and fans',
    'Building Material': 'Cement, plywood, tiles',
    'Paints & Finishes': 'Paints, primers and adhesives',
    'Hardware': 'Locks, hinges, fasteners',
}

# (name, sku, category, hsn, unit, gst %, sale price, vendor index)
ITEMS = [
    ('GI Pipe 2 inch (6 m)', 'PLB-GIP-02', 'Plumbing', '7306', 'PCS', 18, 1450, 0),
    ('CPVC Pipe 1 inch (3 m)', 'PLB-CPV-01', 'Plumbing', '3917', 'PCS', 18, 385, 0),
    ('PVC Fitting Set', 'PLB-FIT-SET', 'Plumbing', '3917', 'SET', 18, 260, 0),
    ('Copper Wire 1.5 sq mm (90 m)', 'ELE-WIR-15', 'Electricals', '8544', 'ROL', 18, 1890, 2),
    ('Copper Wire 2.5 sq mm (90 m)', 'ELE-WIR-25', 'Electricals', '8544', 'ROL', 18, 2980, 2),
    ('LED Panel 18W', 'ELE-LED-18', 'Electricals', '9405', 'PCS', 12, 620, 4),
    ('Ceiling Fan 1200 mm', 'ELE-FAN-12', 'Electricals', '8414', 'NOS', 18, 2350, 4),
    ('MCB 32A Double Pole', 'ELE-MCB-32', 'Electricals', '8536', 'PCS', 18, 540, 2),
    ('Modular Switch 6A', 'ELE-SWT-06', 'Electricals', '8536', 'PCS', 18, 85, 2),
    ('OPC Cement 53 Grade (50 kg)', 'BLD-CEM-53', 'Building Material', '2523', 'BAG', 28, 410, 0),
    ('Commercial Plywood 18 mm 8x4', 'BLD-PLY-18', 'Building Material', '4412', 'PCS', 18, 2450, 3),
    ('Vitrified Tile 600x600 (Box)', 'BLD-TIL-60', 'Building Material', '6907', 'BOX', 18, 980, 3),
    ('Interior Emulsion 20 L', 'PNT-EMU-20', 'Paints & Finishes', '3209', 'BTL', 18, 3200, 1),
    ('Wall Primer 10 L', 'PNT-PRM-10', 'Paints & Finishes', '3209', 'BTL', 18, 1150, 1),
    ('Wood Adhesive 1 kg', 'PNT-ADH-01', 'Paints & Finishes', '3506', 'PCS', 18, 215, 1),
    ('Mortise Door Lock', 'HRD-LCK-MT', 'Hardware', '8301', 'NOS', 18, 1420, 0),
    ('SS Butt Hinge 4 inch (Pair)', 'HRD-HNG-04', 'Hardware', '8302', 'PRS', 18, 95, 0),
    ('Self Tapping Screw (Box of 500)', 'HRD-SCR-500', 'Hardware', '7318', 'BOX', 18, 175, 0),
]

STREETS = ['Lamington Road', 'Station Road', 'MIDC Industrial Area', 'LBS Marg',
           'SV Road', 'Ring Road', 'MG Road', 'Link Road', 'Old Market Lane']

NOTES = ['Thank you for your business.', 'Goods once sold will be exchanged only with the bill.',
         'Please quote the invoice number when paying.', '']
TERMS = ('Payment due within the credit period. Interest at 18% p.a. on overdue amounts. '
         'Subject to Mumbai jurisdiction.')

CENT = Decimal('0.01')


def money(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def make_pan(name, kind='C'):
    """PAN-shaped string: 3 letters, entity type, initial, 4 digits, letter."""
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    initial = next((ch for ch in name.upper() if ch.isalpha()), 'A')
    return (''.join(random.choice(letters) for _ in range(3)) + kind + initial
            + f'{random.randint(1000, 9999)}' + random.choice(letters))


def make_gstin(state_code, name, kind='F'):
    first14 = f'{state_code:02d}{make_pan(name, kind)}1Z'
    return first14 + gstin_check_char(first14)


class Command(BaseCommand):
    help = 'Seed a realistic, untagged year of business data into an account (wipe with --wipe).'

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True, help='username or email')
        parser.add_argument('--months', type=int, default=12)
        parser.add_argument('--per-month', type=int, default=12, help='sales invoices per month (approx.)')
        parser.add_argument('--fix-company', action='store_true',
                            help='replace placeholder/invalid company profile values (address, '
                                 'GSTIN, state, bank, LUT) with realistic Mumbai ones')
        parser.add_argument('--wipe', action='store_true', help='delete what a previous run created')
        parser.add_argument('--random-seed', type=int, default=None)

    # ── setup ─────────────────────────────────────────────────────────

    def handle(self, *args, **opts):
        if opts['random_seed'] is not None:
            random.seed(opts['random_seed'])
        ident = opts['user']
        user = (User.objects.filter(username=ident).first()
                or User.objects.filter(email__iexact=ident).first())
        if not user:
            raise CommandError(f'No user matches {ident!r}.')
        company = user.user_company
        if not company:
            raise CommandError(f'{user.username} has no company yet.')
        self.user, self.company = user, company
        self.path = self.manifest_path(company)

        if opts['wipe']:
            return self.wipe()
        if self.path.exists():
            raise CommandError(f'A previous run is still recorded in {self.path}. '
                               'Run with --wipe first.')

        self.created = {}
        with transaction.atomic():
            if opts['fix_company']:
                self.fix_company()
            if not (isinstance(company.state_code, int) and 1 <= company.state_code <= 38):
                raise CommandError(f'Company state_code is {company.state_code!r}; pass --fix-company '
                                   'or set a real state under My Company first.')
            self.seed(opts['months'], opts['per_month'])
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.created, indent=1))
        self.report()

    @staticmethod
    def manifest_path(company):
        return Path(settings.BASE_DIR) / 'logs' / 'seed_runs' / f'company_{company.id}.json'

    def track(self, obj):
        self.created.setdefault(type(obj).__module__ + '.' + type(obj).__name__, []).append(obj.pk)
        return obj

    def contact(self, slug):
        local, _, domain = (self.user.email or 'owner@gmail.com').partition('@')
        local = local.split('+')[0]
        slug = ''.join(ch for ch in slug.lower() if ch.isalnum())[:20]
        return f'{local}+{slug}@{domain}', (self.user.mobile_number or None)

    def fix_company(self):
        c = self.company
        c.company_address = '14, Shree Niketan, Lamington Road, Grant Road East, Mumbai 400007'
        c.state, c.state_code = 'Maharashtra', 27
        c.company_gst_number = make_gstin(27, c.company_name or 'Aarti')
        c.bank_name, c.branch = 'HDFC Bank', 'Grant Road'
        c.account_number = f'5020{random.randint(10**9, 10**10 - 1)}'
        c.ifsc_code = 'HDFC0000060'
        fy = date.today().year if date.today().month >= 4 else date.today().year - 1
        c.lut_number = f'AD27{str(fy)[2:]}04{random.randint(10**6, 10**7 - 1)}X'
        c.lut_valid_from, c.lut_valid_to = date(fy, 4, 1), date(fy + 1, 3, 31)
        c.save()
        self.stdout.write(f'  Company profile set: Maharashtra (27), GSTIN {c.company_gst_number}')

    # ── seeding ───────────────────────────────────────────────────────

    def seed(self, months, per_month):
        self.cols = self.columns()
        self.customers = self.parties(Customers, CUSTOMERS)
        self.vendors = self.parties(Vendor, [v + ('other',) for v in VENDORS])
        self.stock = self.inventory()
        self.sales = self.make_sales(months, per_month)
        self.purchases = self.make_purchases(months)
        self.notes = self.make_notes()
        self.stock_movements()

    def columns(self):
        """Use the account's own line-item columns; add HSN and Unit if missing."""
        wanted = [('Description', 200, False), ('HSN Code', 60, False), ('Quantity', 40, True),
                  ('Unit', 40, False), ('Rate', 60, True), ('GST', 40, True)]
        cols = {}
        for title, size, calc in wanted:
            col = new_product_in_frontend.objects.filter(user=self.user, input_title__iexact=title).first()
            if col is None:
                col = self.track(new_product_in_frontend.objects.create(
                    user=self.user, input_title=title, size=Decimal(size),
                    is_show=True, is_calculable=calc))
            cols[title] = col
        return cols

    def parties(self, model, rows):
        out = []
        for name, legal, city, code, treatment, btype in rows:
            email, phone = self.contact(name.split()[0])
            gst = make_gstin(code, legal or name) if treatment in ('registered', 'composition', 'sez') else ''
            state = 'Other Countries' if code == 96 else STATE_NAMES.get(code, '')
            out.append(self.track(model.objects.create(
                user=self.user, name=name, legal_name=legal, email=email, phone_number=phone,
                address=(f'Office 702, Al Fahidi Street' if code == 96 else
                         f'{random.randint(1, 250)}, {random.choice(STREETS)}'),
                city=city, state=state, state_code=code,
                pincode='' if code == 96 else str(random.randint(400001, 600099)),
                gst_number=gst, gst_treatment=treatment,
                pan_number=gst[2:12] if gst else '',
                business_type=btype,
            )))
        return out

    def inventory(self):
        cats = {n: self.track(Category.objects.create(company=self.company, name=n, description=d))
                for n, d in CATEGORIES.items()}
        sups = []
        for v in self.vendors[:5]:
            sups.append(self.track(Supplier.objects.create(
                company=self.company, name=v.name, contact_person=random.choice(
                    ['Ramesh Iyer', 'Suresh Shah', 'Anil Mehta', 'Pooja Nair', 'Vikram Rao']),
                email=v.email, phone=v.phone_number, address=f'{v.address}, {v.city}')))
        items = []
        for name, sku, cat, hsn, unit, gst, price, vi in ITEMS:
            items.append(self.track(StockItem.objects.create(
                company=self.company, sku=sku, name=name, description=name,
                category=cats[cat], supplier=sups[vi % len(sups)], vendor=self.vendors[vi],
                price=Decimal(price), gst_percentage=Decimal(gst), hsn_code=hsn, unit=unit,
                current_stock=0, reorder_level=random.choice([10, 15, 20, 25]))))
        self.out_qty = {i.pk: 0 for i in items}
        return items

    def line(self, item, qty, zero_rated=False, price=None):
        rate = money(price if price is not None else Decimal(item.price) * Decimal(random.uniform(0.95, 1.05)))
        gst = 0 if zero_rated else int(item.gst_percentage)
        p = self.track(Product.objects.create(user=self.user, gst_amount=0, total_amount=0))
        for title, value in (('Description', item.name), ('HSN Code', item.hsn_code),
                             ('Quantity', str(qty)), ('Unit', item.unit),
                             ('Rate', str(rate)), ('GST', str(gst))):
            p.product_properties.add(self.track(Product_properties.objects.create(
                new_product_in_frontend=self.cols[title], value=value)))
        recompute_product(p)
        return p

    @staticmethod
    def month_window(today, back):
        idx = today.year * 12 + today.month - 1 - back
        y, m = idx // 12, idx % 12 + 1
        return date(y, m, 1), min(date(y, m, monthrange(y, m)[1]), today)

    def status_for(self, when, due, today):
        age = (today - when).days
        r = random.random()
        if age > 60:
            s = 'paid' if r < 0.85 else ('partially_paid' if r < 0.92 else 'unpaid')
        elif age > 25:
            s = 'paid' if r < 0.6 else ('partially_paid' if r < 0.8 else 'unpaid')
        else:
            s = 'paid' if r < 0.3 else ('partially_paid' if r < 0.5 else 'unpaid')
        if s == 'unpaid' and due < today:
            s = 'overdue'
        return s

    def make_sales(self, months, per_month):
        today = date.today()
        weights = [6, 6, 5, 5, 5, 4, 4, 3, 3, 3, 3, 3, 1, 1]  # big accounts buy more often
        dates = []
        for back in range(months - 1, -1, -1):
            start, end = self.month_window(today, back)
            # gentle seasonality: busier Oct–Mar
            n = max(4, int(random.gauss(per_month * (1.25 if start.month in (10, 11, 12, 1, 2, 3) else 0.85), 2)))
            dates += [start + timedelta(days=random.randint(0, (end - start).days)) for _ in range(n)]
        dates.sort()

        out = []
        for when in dates:
            cust = random.choices(self.customers, weights=weights)[0]
            b2c = cust.gst_treatment in ('consumer', 'unregistered')
            zero = cust.gst_treatment in ('sez', 'overseas')   # supplied under LUT
            n_lines = random.randint(1, 2) if b2c else random.randint(2, 6)
            picks = random.sample(self.stock, n_lines)
            lines = []
            for item in picks:
                qty = random.randint(1, 4) if b2c else random.randint(5, 60)
                if item.unit == 'BAG' and not b2c:
                    qty *= 3
                lines.append(self.line(item, qty, zero_rated=zero))
                self.out_qty[item.pk] += qty
            credit = 0 if b2c else random.choice([15, 30, 30, 45])
            due = when + timedelta(days=credit)
            inv = self.track(Invoice.objects.create(
                user=self.user, receiver=cust, date=when, due_date=due, invoice_type='sales',
                invoice_number=next_invoice_number(self.company, when),
                place_of_supply=cust.state_code,
                customer_notes=random.choice(NOTES), terms='' if b2c else TERMS,
                total_final_amount=0, gst_final_amount=0,
            ))
            inv.products.set(lines)
            recompute_invoice_totals(inv)
            inv.refresh_from_db()
            status = 'paid' if b2c else self.status_for(when, due, today)
            method = random.choice(['cash', 'upi']) if b2c else random.choice(
                ['bank_transfer', 'bank_transfer', 'upi', 'cheque'])
            if cust.gst_treatment == 'overseas':
                method = 'bank_transfer'
            inv.payment_status = status
            inv.payment_method = method if status != 'unpaid' and status != 'overdue' else None
            inv.save(update_fields=['payment_status', 'payment_method'])
            self.pay(inv, status, method, 'received', when, today)
            out.append(inv)
        return out

    def make_purchases(self, months):
        today = date.today()
        out = []
        goods_vendors = self.vendors[:5]
        for back in range(months - 1, -1, -1):
            start, end = self.month_window(today, back)
            for _ in range(random.randint(2, 3)):
                when = start + timedelta(days=random.randint(0, (end - start).days))
                vendor = random.choice(goods_vendors)
                vi = self.vendors.index(vendor)
                items = [i for i, row in zip(self.stock, ITEMS) if row[7] == vi] or self.stock
                lines = [self.line(it, random.randint(20, 120), price=money(Decimal(it.price) * Decimal('0.78')))
                         for it in random.sample(items, min(len(items), random.randint(1, 4)))]
                prefix = ''.join(w[0] for w in vendor.name.split()[:2]).upper()
                out.append(self.purchase(vendor, when, f'{prefix}/{when:%y%m}/{random.randint(100, 999)}',
                                         lines, False, today))
            if back % 2 == 0:   # freight from an unregistered transporter: reverse charge
                when = start + timedelta(days=random.randint(0, (end - start).days))
                freight = self.freight_line(random.choice([3500, 4800, 6200]))
                out.append(self.purchase(self.vendors[5], when, f'LR-{random.randint(1000, 9999)}',
                                         [freight], True, today))
        return out

    def freight_line(self, amount):
        p = self.track(Product.objects.create(user=self.user, gst_amount=0, total_amount=0))
        for title, value in (('Description', 'Goods transport (GTA) freight'), ('HSN Code', '996511'),
                             ('Quantity', '1'), ('Unit', 'NOS'), ('Rate', str(amount)), ('GST', '5')):
            p.product_properties.add(self.track(Product_properties.objects.create(
                new_product_in_frontend=self.cols[title], value=value)))
        recompute_product(p)
        return p

    def purchase(self, vendor, when, number, lines, rcm, today):
        due = when + timedelta(days=30)
        inv = self.track(Invoice.objects.create(
            user=self.user, vendor=vendor, date=when, due_date=due, invoice_type='purchase',
            invoice_number=number, reverse_charge=rcm, place_of_supply=self.company.state_code,
            total_final_amount=0, gst_final_amount=0))
        inv.products.set(lines)
        recompute_invoice_totals(inv)
        inv.refresh_from_db()
        status = self.status_for(when, due, today)
        method = 'cash' if rcm else random.choice(['bank_transfer', 'cheque', 'upi'])
        inv.payment_status = status
        inv.payment_method = method if status in ('paid', 'partially_paid') else None
        inv.save(update_fields=['payment_status', 'payment_method'])
        self.pay(inv, status, method, 'made', when, today)
        return inv

    def pay(self, inv, status, method, direction, when, today):
        if status not in ('paid', 'partially_paid'):
            return
        total = Decimal(inv.total_final_amount)
        amount = total if status == 'paid' else money(total * Decimal(random.choice(['0.3', '0.5', '0.6'])))
        paid_on = min(when + timedelta(days=random.randint(0, 25)), today)
        ref = {
            'upi': f'UPI/{random.randint(10**11, 10**12 - 1)}',
            'bank_transfer': f'NEFT/HDFCN{paid_on:%y%m%d}{random.randint(10**5, 10**6 - 1)}',
            'cheque': f'CHQ {random.randint(100000, 999999)}',
            'cash': '',
        }.get(method, '')
        self.track(Payment.objects.create(
            user=self.user, company=self.company, invoice=inv, payment_type=direction,
            amount=amount, date=paid_on, payment_method=method, reference_number=ref,
            customer=inv.receiver if direction == 'received' else None,
            vendor=inv.vendor if direction == 'made' else None,
        ))

    def make_notes(self):
        notes = []
        b2b = [i for i in self.sales if i.receiver.gst_treatment in ('registered', 'composition')
               and Decimal(i.gst_final_amount) > 0]
        reasons = {'credit': ['Goods returned - damaged in transit', 'Rate difference',
                              'Post-sale discount on volume'],
                   'debit': ['Short billing on rate', 'Additional freight charged']}
        counters = {'credit': 0, 'debit': 0}
        for i, inv in enumerate(random.sample(b2b, min(6, len(b2b)))):
            kind = 'debit' if i in (2, 5) else 'credit'
            counters[kind] += 1
            share = Decimal(random.choice(['0.05', '0.08', '0.1']))
            gst = money(Decimal(inv.gst_final_amount) * share)
            notes.append(self.track(CreditDebitNote.objects.create(
                user=self.user, company=self.company, invoice=inv, customer=inv.receiver,
                note_type=kind, note_number=f'{"CN" if kind == "credit" else "DN"}-{counters[kind]:04d}',
                amount=money(Decimal(inv.total_final_amount) * share), gst_amount=gst,
                date=min(inv.date + timedelta(days=random.randint(3, 20)), date.today()),
                reason=random.choice(reasons[kind]),
            )))
        return notes

    def stock_movements(self):
        """Opening stock covers what was sold, leaving some items near reorder level."""
        opening = timezone.make_aware(datetime.combine(date.today() - timedelta(days=370), time(10)))
        for n, item in enumerate(self.stock):
            sold = self.out_qty[item.pk]
            left = (random.randint(0, item.reorder_level) if n % 4 == 0
                    else random.randint(item.reorder_level + 10, item.reorder_level + 150))
            mv = self.track(StockMovement.objects.create(
                product=item, quantity=sold + left, movement_type='IN', notes='Opening stock'))
            StockMovement.objects.filter(pk=mv.pk).update(date=opening)
        # one OUT per invoiced inventory line, dated like the invoice, noted like the apps do
        by_name = {i.name: i for i in self.stock}
        for inv in self.sales:
            for p in inv.products.all():
                vals = {pp.new_product_in_frontend_id: pp.value for pp in p.product_properties.all()}
                item = by_name.get(vals.get(self.cols['Description'].id))
                if not item:
                    continue
                mv = self.track(StockMovement.objects.create(
                    product=item, quantity=int(vals[self.cols['Quantity'].id]),
                    movement_type='OUT', notes=f'Invoice #{inv.id}'))
                StockMovement.objects.filter(pk=mv.pk).update(
                    date=timezone.make_aware(datetime.combine(inv.date, time(12))))

    # ── output ────────────────────────────────────────────────────────

    def report(self):
        tot = sum(Decimal(i.total_final_amount) for i in self.sales)
        gst = sum(Decimal(i.gst_final_amount) for i in self.sales)
        owing = sum(1 for i in self.sales if i.payment_status != 'paid')
        overdue = sum(1 for i in self.sales if i.payment_status == 'overdue')
        for s in self.stock:
            s.refresh_from_db()
        low = sum(1 for s in self.stock if s.current_stock <= s.reorder_level)
        w = self.stdout.write
        w(f'  {len(self.customers)} customers, {len(self.vendors)} vendors')
        w(f'  {len(self.sales)} sales invoices  ₹{tot:,.0f} (GST ₹{gst:,.0f}), {owing} owing, {overdue} overdue')
        w(f'  {len(self.purchases)} purchase bills ({sum(1 for p in self.purchases if p.reverse_charge)} reverse charge)')
        w(f'  {len(self.created.get("invoice.models.Payment", []))} payments, {len(self.notes)} credit/debit notes')
        w(f'  {len(self.stock)} inventory items, {low} at or below reorder level')
        w(self.style.SUCCESS(f'Done. Manifest: {self.path}  (remove with --wipe)'))

    # ── wipe ──────────────────────────────────────────────────────────

    def wipe(self):
        if not self.path.exists():
            raise CommandError(f'No manifest at {self.path}; nothing recorded to remove.')
        created = json.loads(self.path.read_text())
        # children first; movements are hard-deleted with their items (no stock reversal needed)
        order = ['invoice.models.Payment', 'invoice.models.CreditDebitNote',
                 'inventory.models.StockMovement', 'inventory.models.Product',
                 'inventory.models.Supplier', 'inventory.models.Category',
                 'invoice.models.Invoice', 'invoice.models.Product',
                 'invoice.models.Product_properties', 'companies.models.Customers',
                 'companies.models.Vendor', 'invoice.models.new_product_in_frontend']
        models = {f'{m.__module__}.{m.__name__}': m for m in (
            Payment, CreditDebitNote, StockMovement, StockItem, Supplier, Category, Invoice,
            Product, Product_properties, Customers, Vendor, new_product_in_frontend)}
        with transaction.atomic():
            for key in order:
                ids = created.get(key) or []
                if not ids:
                    continue
                model = models[key]
                qs = getattr(model, 'all_objects', model.objects).filter(pk__in=ids)
                n = qs.count()
                (getattr(qs, 'hard_delete', None) or qs.delete)()
                self.stdout.write(f'  {n:>6}  {model.__name__}')
        self.path.unlink()
        self.stdout.write(self.style.SUCCESS('Removed everything the seed run created.'))
