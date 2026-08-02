"""
Seed realistic demo data into any account.

    python manage.py seed_demo_data --user aarti
    python manage.py seed_demo_data --company 9 --months 6 --invoices 8
    python manage.py seed_demo_data --user aarti --wipe

Everything created is tagged so it can be removed again without touching
real records — see `TAG_NOTE`. The tag is deliberately visible in names,
invoice numbers and SKUs: if you're staring at a dashboard you should be
able to tell at a glance which rows are fake.

The generated data is *clean* on purpose — valid GST state codes, tax at
real slabs, line items that reconcile to the invoice header — so that the
CGST/SGST/IGST split and the receivables/overdue figures all populate with
numbers you can check by hand.
"""
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User, UserCompanies
from companies.models import Customers, Vendor
from inventory.models import Category, Product as StockItem, StockMovement, Supplier
from invoice.models import (CreditDebitNote, Invoice, Payment, Product,
                            Product_properties, new_product_in_frontend)

# ── how seeded rows are recognised again ──────────────────────────────
#
# Each model carries the tag somewhere natural and human-visible rather
# than in a hidden column, so `--wipe` is exact and the data is obviously
# fake when you look at it.
TAG_NOTE = """
  Customers / Vendors  name ends with  "[<tag>]"
  Invoices             invoice_number starts with  "<TAG>-"
  Payments             reference_number starts with  "<TAG>-"
  Credit/Debit notes   note_number starts with  "<TAG>-"
  Inventory items      sku starts with  "<TAG>-"
  Categories/Suppliers name ends with  "[<tag>]"
"""

# Real GST slabs. Nothing else is legal, so nothing else is generated.
GST_SLABS = (Decimal('5'), Decimal('12'), Decimal('18'), Decimal('28'))

# (state name, GSTIN state code) — all valid codes in the 01–38 range
STATES = [
    ('Maharashtra', 27), ('Karnataka', 29), ('Delhi', 7), ('Gujarat', 24),
    ('Tamil Nadu', 33), ('Uttar Pradesh', 9), ('West Bengal', 19),
    ('Rajasthan', 8), ('Telangana', 36), ('Kerala', 32), ('Punjab', 3),
    ('Haryana', 6), ('Madhya Pradesh', 23), ('Bihar', 10),
]

CUSTOMER_NAMES = [
    'Zenith Traders', 'Sunrise Distributors', 'Kamal Hardware',
    'Meridian Retail', 'Patel & Sons', 'Blue Orchid Foods',
    'Sharma Electricals', 'Nova Textiles', 'Greenleaf Organics',
    'Deccan Auto Parts', 'Ravi Steel Works', 'Coastal Marine Supply',
]

VENDOR_NAMES = [
    'Apex Raw Materials', 'Sundar Packaging', 'Trident Wholesale',
    'Iyer Logistics', 'Bharat Paper Mills', 'Orion Components',
]

ITEMS = [
    ('Steel Pipe 2in', 'PIPE', 450), ('Copper Wire 10m', 'WIRE', 890),
    ('LED Panel 18W', 'LED', 620), ('Cement Bag 50kg', 'CEM', 410),
    ('Plywood Sheet 8x4', 'PLY', 1750), ('Paint Bucket 20L', 'PNT', 3200),
    ('Ceramic Tile Box', 'TILE', 980), ('PVC Fitting Set', 'PVC', 260),
    ('Hinge Pack 12', 'HNG', 340), ('Adhesive Tube 1kg', 'ADH', 215),
    ('Door Lock Premium', 'LCK', 1420), ('Steel Screw 500pc', 'SCR', 175),
]

CATEGORIES = ['Hardware', 'Electricals', 'Building Material', 'Finishes']

PAYMENT_METHODS = ('cash', 'upi', 'bank_transfer', 'cheque', 'card')


def money(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = ("Seed tagged demo data (customers, vendors, invoices, payments, "
            "notes, inventory) into an account. Use --wipe to remove it.")

    def add_arguments(self, parser):
        target = parser.add_argument_group('target account (one required)')
        target.add_argument('--user', help='username or email of any user in the account')
        target.add_argument('--company', help='UserCompanies id or exact company name')

        parser.add_argument('--tag', default='demo',
                            help='marker written into seeded records (default: demo)')
        parser.add_argument('--months', type=int, default=12,
                            help='how many months back to spread invoices (default: 12)')
        parser.add_argument('--invoices', type=int, default=10,
                            help='approximate sales invoices per month (default: 10)')
        parser.add_argument('--customers', type=int, default=10)
        parser.add_argument('--vendors', type=int, default=5)
        parser.add_argument('--random-seed', type=int, default=None,
                            help='fix the RNG for reproducible output')

        parser.add_argument('--wipe', action='store_true',
                            help='delete previously seeded rows for this tag, then exit')
        parser.add_argument('--dry-run', action='store_true',
                            help='report what would happen and roll back')
        parser.add_argument('--fix-company-state', type=int, metavar='CODE',
                            help='set the company state_code (needed for the CGST/SGST '
                                 'vs IGST split to populate); only pass a real code 1-38')

    # ── entry point ───────────────────────────────────────────────────

    def handle(self, *args, **opts):
        self.tag = opts['tag']
        self.prefix = self.tag.upper()
        self.suffix = f'[{self.tag}]'

        if opts['random_seed'] is not None:
            random.seed(opts['random_seed'])

        user, company = self.resolve_target(opts)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Account: {company.company_name if company else "(no company)"} '
            f'· acting user: {user.username} · tag: {self.tag}'))

        if opts['wipe']:
            self.wipe(user, company, dry_run=opts['dry_run'])
            return

        try:
            with transaction.atomic():
                self.seed(user, company, opts)
                if opts['dry_run']:
                    self.stdout.write(self.style.WARNING(
                        '\n--dry-run: rolling back, nothing was saved.'))
                    transaction.set_rollback(True)
        except Exception as exc:                    # noqa: BLE001
            raise CommandError(f'Seeding failed, nothing was saved: {exc}') from exc

    # ── target resolution ─────────────────────────────────────────────

    def resolve_target(self, opts):
        if not opts['user'] and not opts['company']:
            raise CommandError('Pass --user <username|email> or --company <id|name>.')

        user = None
        if opts['user']:
            ident = opts['user']
            user = (User.objects.filter(username=ident).first()
                    or User.objects.filter(email__iexact=ident).first())
            if not user:
                raise CommandError(f'No user matches {ident!r}.')
            company = user.user_company

        else:
            ident = opts['company']
            company = (UserCompanies.objects.filter(pk=ident).first()
                       if str(ident).isdigit() else None)
            company = company or UserCompanies.objects.filter(company_name=ident).first()
            if not company:
                raise CommandError(f'No company matches {ident!r}.')
            # invoices hang off a user, so pick the company's admin
            user = (User.objects.filter(user_company=company, is_company_admin=True)
                    .order_by('id').first()
                    or User.objects.filter(user_company=company).order_by('id').first())
            if not user:
                raise CommandError(
                    f'Company {company.company_name!r} has no users to attribute data to.')

        if company is None:
            raise CommandError(
                f'{user.username} has no company yet. Create the company profile '
                'first (My Company), otherwise inventory and payments have nowhere '
                'to attach.')

        return user, company

    # ── seeding ───────────────────────────────────────────────────────

    def seed(self, user, company, opts):
        if opts['fix_company_state'] is not None:
            code = opts['fix_company_state']
            if not 1 <= code <= 38:
                raise CommandError('--fix-company-state must be a real code, 1-38.')
            company.state_code = code
            company.state = next((n for n, c in STATES if c == code), company.state)
            company.save(update_fields=['state_code', 'state'])
            self.stdout.write(self.style.SUCCESS(
                f'  Set company state to {company.state} ({code}).'))

        home_code = company.state_code
        if not (isinstance(home_code, int) and 1 <= home_code <= 38):
            self.stdout.write(self.style.WARNING(
                f'  ! Company state_code is {home_code!r}, which is not a valid GST '
                'code (1-38).\n'
                '    Sales will seed fine but the CGST/SGST vs IGST split cannot be\n'
                '    computed until this is fixed. Re-run with --fix-company-state 27\n'
                '    (or set it under My Company).'))
            home_code = random.choice(STATES)[1]   # still split customers sensibly

        fields = self.ensure_line_item_fields(user)
        customers = self.make_parties(Customers, user, CUSTOMER_NAMES,
                                      opts['customers'], home_code, intra_ratio=0.6)
        vendors = self.make_parties(Vendor, user, VENDOR_NAMES,
                                    opts['vendors'], home_code, intra_ratio=0.5)
        self.stdout.write(f'  {len(customers)} customers, {len(vendors)} vendors')

        sales = self.make_sales(user, company, customers, fields,
                                opts['months'], opts['invoices'])
        purchases = self.make_purchases(user, company, vendors, fields, opts['months'])
        notes = self.make_notes(user, company, sales)
        stock = self.make_inventory(company, vendors)

        self.report(sales, purchases, notes, stock, home_code)

    def ensure_line_item_fields(self, user):
        """The column definitions an invoice line is described by."""
        wanted = [
            ('Description', 200, False),
            ('Quantity', 10, False),
            ('Rate', 20, False),
            ('Amount', 20, True),
        ]
        out = {}
        for title, size, calculable in wanted:
            obj, _ = new_product_in_frontend.objects.get_or_create(
                user=user, input_title=title,
                defaults={'size': Decimal(size), 'is_show': True,
                          'is_calculable': calculable})
            out[title] = obj
        return out

    def make_parties(self, model, user, names, count, home_code, intra_ratio):
        """Customers or vendors — every one gets a valid state code."""
        parties = []
        pool = names[:] * 2
        for i in range(count):
            base = pool[i % len(pool)]
            name = f'{base} {self.suffix}' if i < len(names) else f'{base} {i} {self.suffix}'

            # a deliberate mix so both tax buckets are exercised
            if random.random() < intra_ratio:
                state_name = next((n for n, c in STATES if c == home_code), 'Maharashtra')
                state_code = home_code
            else:
                state_name, state_code = random.choice(
                    [s for s in STATES if s[1] != home_code])

            obj, _ = model.objects.get_or_create(
                user=user, name=name,
                defaults={
                    'legal_name': base,
                    'email': f'{base.lower().replace(" ", ".").replace("&", "and")}@example.com',
                    'phone_number': f'9{random.randint(100000000, 999999999)}',
                    'address': f'{random.randint(1, 400)}, {random.choice(["MG Road", "Station Road", "Industrial Estate", "Ring Road"])}',
                    'city': state_name,
                    'state': state_name,
                    'state_code': state_code,
                    'pincode': str(random.randint(110001, 799999)),
                    'gst_number': self.fake_gstin(state_code),
                    'business_type': random.choice(
                        ['private_limited', 'partnership', 'sole_prop', 'llp']),
                },
            )
            parties.append(obj)
        return parties

    @staticmethod
    def fake_gstin(state_code):
        letters = ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(5))
        return (f'{state_code:02d}{letters}{random.randint(1000, 9999)}'
                f'{random.choice("ABCDEFGHIJ")}1Z{random.randint(0, 9)}')

    # ── invoices ──────────────────────────────────────────────────────

    def build_lines(self, fields, count):
        """Line items whose amounts actually add up to the header totals.

        The app's `total_final_amount` is GST-inclusive, so each line's
        `total_amount` includes its own tax and the header is a plain sum.
        """
        lines, taxable_sum, gst_sum = [], Decimal('0'), Decimal('0')

        for _ in range(count):
            name, _code, rate = random.choice(ITEMS)
            qty = Decimal(random.randint(1, 25))
            unit = money(Decimal(rate) * Decimal(random.uniform(0.9, 1.15)))
            slab = random.choice(GST_SLABS)

            taxable = money(qty * unit)
            gst = money(taxable * slab / 100)
            total = money(taxable + gst)

            product = Product.objects.create(gst_amount=gst, total_amount=total)
            for title, value in (('Description', name), ('Quantity', str(qty)),
                                 ('Rate', str(unit)), ('Amount', str(total))):
                product.product_properties.add(
                    Product_properties.objects.create(
                        new_product_in_frontend=fields[title], value=value))

            lines.append(product)
            taxable_sum += taxable
            gst_sum += gst

        return lines, money(taxable_sum + gst_sum), money(gst_sum)

    @staticmethod
    def month_window(today, months_back):
        """First and last day of the month `months_back` before `today`.

        Done with real month arithmetic rather than `days=30 * n`, which
        drifts and would smear each month's invoices across the whole span.
        """
        from calendar import monthrange
        idx = today.year * 12 + (today.month - 1) - months_back
        year, month = idx // 12, (idx % 12) + 1
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        return start, min(end, today)

    def make_sales(self, user, company, customers, fields, months, per_month):
        today = date.today()
        created = []
        counter = 1

        for back in range(months - 1, -1, -1):
            start, end = self.month_window(today, back)
            n = max(1, int(random.gauss(per_month, per_month * 0.3)))

            for _ in range(n):
                when = start + timedelta(days=random.randint(0, (end - start).days))

                lines, total, gst = self.build_lines(fields, random.randint(1, 5))
                status, method = self.pick_status(when, today)

                inv = Invoice.objects.create(
                    user=user,
                    receiver=random.choice(customers),
                    invoice_number=f'{self.prefix}-S{counter:05d}',
                    date=when,
                    invoice_type='sales',
                    total_final_amount=total,
                    gst_final_amount=gst,
                    payment_status=status,
                    payment_method=method,
                )
                inv.products.set(lines)
                created.append(inv)
                counter += 1

                self.record_payment(user, company, inv, status, method, when, 'received')

        return created

    def make_purchases(self, user, company, vendors, fields, months):
        """Purchases always carry input GST — a zero would understate ITC."""
        today = date.today()
        created = []

        for i in range(max(months // 2, 3)):
            when = today - timedelta(days=random.randint(0, months * 30))
            lines, total, gst = self.build_lines(fields, random.randint(1, 3))
            status, method = self.pick_status(when, today)

            inv = Invoice.objects.create(
                user=user,
                vendor=random.choice(vendors),
                invoice_number=f'{self.prefix}-P{i + 1:05d}',
                date=when,
                invoice_type='purchase',
                total_final_amount=total,
                gst_final_amount=gst,
                payment_status=status,
                payment_method=method,
            )
            inv.products.set(lines)
            created.append(inv)

            self.record_payment(user, company, inv, status, method, when, 'made')

        return created

    @staticmethod
    def pick_status(when, today):
        age = (today - when).days
        roll = random.random()
        if age > 45:
            status = 'paid' if roll < 0.8 else 'unpaid'
        elif age > 20:
            status = 'paid' if roll < 0.55 else ('partially_paid' if roll < 0.8 else 'unpaid')
        else:
            status = 'paid' if roll < 0.35 else ('partially_paid' if roll < 0.6 else 'unpaid')
        method = random.choice(PAYMENT_METHODS) if status != 'unpaid' else None
        return status, method

    def record_payment(self, user, company, inv, status, method, when, direction):
        """Money actually moved, so the outstanding figures net correctly."""
        if status == 'unpaid':
            return
        total = Decimal(inv.total_final_amount)
        amount = total if status == 'paid' else money(total * Decimal(
            random.choice(['0.25', '0.4', '0.5', '0.7'])))

        Payment.objects.create(
            user=user, company=company, invoice=inv,
            payment_type=direction,
            amount=amount,
            date=when + timedelta(days=random.randint(0, 20)),
            payment_method=method or 'cash',
            reference_number=f'{self.prefix}-PAY{inv.id:06d}',
            customer=inv.receiver if direction == 'received' else None,
            vendor=inv.vendor if direction == 'made' else None,
        )

    def make_notes(self, user, company, sales):
        """A few credit/debit notes against real invoices."""
        notes = []
        if not sales:
            return notes
        for i, inv in enumerate(random.sample(sales, min(4, len(sales))), start=1):
            kind = 'credit' if i % 3 else 'debit'
            notes.append(CreditDebitNote.objects.create(
                user=user, company=company, invoice=inv,
                customer=inv.receiver,
                note_type=kind,
                note_number=f'{self.prefix}-{kind[:1].upper()}N{i:04d}',
                amount=money(Decimal(inv.total_final_amount) * Decimal('0.1')),
                date=inv.date + timedelta(days=random.randint(1, 15)),
                reason=random.choice([
                    'Goods returned', 'Rate difference', 'Short supply',
                    'Post-sale discount']),
            ))
        return notes

    # ── inventory ─────────────────────────────────────────────────────

    def make_inventory(self, company, vendors):
        cats = []
        for name in CATEGORIES:
            cat, _ = Category.objects.get_or_create(
                company=company, name=f'{name} {self.suffix}',
                defaults={'description': f'Seeded demo category ({self.tag})'})
            cats.append(cat)

        suppliers = []
        for v in vendors[:3]:
            sup, _ = Supplier.objects.get_or_create(
                company=company, name=f'{v.legal_name or v.name} {self.suffix}',
                defaults={'contact_person': 'Demo Contact', 'email': v.email,
                          'phone': v.phone_number, 'address': v.address})
            suppliers.append(sup)

        items = []
        for i, (name, code, price) in enumerate(ITEMS):
            reorder = random.choice([5, 10, 15, 20])
            # roughly a third sit at or below reorder level so the
            # dashboard's low-stock panel has something to show
            if i % 3 == 0:
                stock = random.randint(0, reorder)
            else:
                stock = random.randint(reorder + 5, reorder + 120)

            item, created = StockItem.objects.get_or_create(
                company=company, sku=f'{self.prefix}-{code}{i + 1:03d}',
                defaults={
                    'name': name,
                    'description': f'Seeded demo item ({self.tag})',
                    'category': random.choice(cats),
                    'supplier': random.choice(suppliers) if suppliers else None,
                    'vendor': random.choice(vendors) if vendors else None,
                    'price': Decimal(price),
                    'gst_percentage': random.choice(GST_SLABS),
                    'current_stock': 0,
                    'reorder_level': reorder,
                },
            )
            items.append(item)

            if created and stock:
                # go through StockMovement so current_stock is derived, not asserted
                StockMovement.objects.create(
                    product=item, quantity=stock, movement_type='IN',
                    notes=f'Opening stock ({self.tag})')

        return items

    # ── reporting ─────────────────────────────────────────────────────

    def report(self, sales, purchases, notes, stock, home_code):
        s_total = sum(Decimal(i.total_final_amount) for i in sales)
        s_gst = sum(Decimal(i.gst_final_amount) for i in sales)
        p_gst = sum(Decimal(i.gst_final_amount) for i in purchases)
        open_n = sum(1 for i in sales if i.payment_status != 'paid')
        low = sum(1 for i in stock if i.current_stock <= i.reorder_level)

        w = self.stdout.write
        w(f'  {len(sales)} sales invoices   ₹{s_total:,.0f} incl. ₹{s_gst:,.0f} GST')
        w(f'  {len(purchases)} purchase invoices   ₹{p_gst:,.0f} input GST')
        w(f'  {open_n} sales invoices still owing')
        w(f'  {len(notes)} credit/debit notes')
        w(f'  {len(stock)} stock items, {low} at or below reorder level')
        w(self.style.SUCCESS('\nDone.'))
        w(f'  Net GST for the whole span: ₹{s_gst - p_gst:,.0f}')
        w(f'  Remove it again with:  --tag {self.tag} --wipe')

    # ── wipe ──────────────────────────────────────────────────────────

    def wipe(self, user, company, dry_run=False):
        """Delete only rows carrying this tag, for this account.

        Uses `all_objects` so previously soft-deleted seed rows go too, and
        `hard_delete` so nothing is left behind as a tombstone.
        """
        pfx, sfx = f'{self.prefix}-', self.suffix
        plan = []

        invoices = Invoice.all_objects.filter(
            user__user_company=company, invoice_number__startswith=pfx)
        # line items and their property rows are M2M — collect the ids before
        # the invoices disappear, and keep them scoped to this tag so a
        # blanket "orphan" cleanup can't touch anyone else's rows
        line_ids = list(Product.objects.filter(
            invoice__in=invoices).values_list('id', flat=True).distinct())
        prop_ids = list(Product_properties.objects.filter(
            product__id__in=line_ids).values_list('id', flat=True).distinct())

        # `receiver` / `vendor` are CASCADE, so deleting a seeded party would
        # take any real invoice pointing at it down too. Exclude those.
        def safe_parties(model, field):
            qs = model.all_objects.filter(
                user__user_company=company, name__endswith=sfx)
            referenced_by_real = (Invoice.all_objects
                                  .filter(**{f'{field}__in': qs})
                                  .exclude(invoice_number__startswith=pfx)
                                  .values_list(f'{field}_id', flat=True))
            protected = set(referenced_by_real)
            if protected:
                self.protected_parties[model.__name__] = len(protected)
            return qs.exclude(id__in=protected)

        self.protected_parties = {}

        plan.append(('payments', Payment.objects.filter(
            company=company, reference_number__startswith=pfx)))
        plan.append(('credit/debit notes', CreditDebitNote.objects.filter(
            company=company, note_number__startswith=pfx)))
        plan.append(('invoices', invoices))
        plan.append(('stock movements', StockMovement.all_objects.filter(
            product__company=company, product__sku__startswith=pfx)))
        plan.append(('stock items', StockItem.all_objects.filter(
            company=company, sku__startswith=pfx)))
        plan.append(('inventory categories', Category.all_objects.filter(
            company=company, name__endswith=sfx)))
        plan.append(('inventory suppliers', Supplier.all_objects.filter(
            company=company, name__endswith=sfx)))
        plan.append(('customers', safe_parties(Customers, 'receiver')))
        plan.append(('vendors', safe_parties(Vendor, 'vendor')))

        counts = [(label, qs.count()) for label, qs in plan]
        counts.append(('invoice line items', len(line_ids)))

        if not any(n for _, n in counts):
            self.stdout.write(self.style.WARNING(
                f'Nothing tagged {self.tag!r} found for this account. '
                f'Tags are recognised as:{TAG_NOTE.replace("<tag>", self.tag).replace("<TAG>", self.prefix)}'))
            return

        for label, n in counts:
            if n:
                self.stdout.write(f'  {n:>6}  {label}')

        for model, n in self.protected_parties.items():
            self.stdout.write(self.style.WARNING(
                f'  keeping {n} seeded {model.lower()}(s): a non-seeded invoice '
                'still references them, and the FK cascades.'))

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run: nothing deleted.'))
            return

        with transaction.atomic():
            for _label, qs in plan:
                hard = getattr(qs, 'hard_delete', None)
                (hard or qs.delete)()
            Product.objects.filter(id__in=line_ids).delete()
            Product_properties.objects.filter(id__in=prop_ids).delete()

        self.stdout.write(self.style.SUCCESS(f'Wiped all {self.tag!r} data.'))
