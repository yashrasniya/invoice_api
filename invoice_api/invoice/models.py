import os
from datetime import datetime

from django.db import models
from django.utils import timezone

from accounts.models import User


from invoice_api.softdelete import SoftDeleteModel
# numbering imports models lazily (inside functions), so this is not a cycle
from invoice import numbering


#: Input tax credit on a purchase (GSTR-3B Table 4). `blocked`: never
#: claimable (s.17(5): motor vehicles, food, personal use, ...), reported in
#: 4A and reversed in 4B(1). `reversal`: claimable later (e.g. the supplier
#: hasn't paid the tax yet), reversed in 4B(2).
ITC_CHOICES = [
    ('eligible', 'Eligible'),
    ('blocked', 'Blocked (s.17(5))'),
    ('reversal', 'Reversed for now'),
]


class Invoice(SoftDeleteModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=30,blank=True,null=True)
    receiver = models.ForeignKey('companies.Customers', on_delete=models.CASCADE,blank=True,null=True)
    vendor = models.ForeignKey('companies.Vendor', on_delete=models.CASCADE,blank=True,null=True)
    date = models.DateField(null=True,blank=True)
    products = models.ManyToManyField('Product',blank=True,null=True)  # connect to Product model
    gst_final_amount = models.DecimalField(max_digits=20,decimal_places=2,null=True)
    total_final_amount = models.DecimalField(max_digits=20,decimal_places=2,null=True)
    custom_header_field = models.JSONField(blank=True, null=True, default=dict)
    due_date = models.DateField(null=True, blank=True)
    # GST state code (01-38, 97, 99) of the place of supply. Null means "same
    # as the customer's state", which is what the GST split falls back to.
    place_of_supply = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="GST state code of the place of supply")
    # shown to the customer on the invoice (`notes` is taken: credit/debit notes' reverse accessor)
    # Reverse charge: the recipient pays the GST. gst_final_amount is that
    # tax; total_final_amount is what is payable to the supplier, without it.
    reverse_charge = models.BooleanField(default=False)
    # purchases only: whether the GST on this bill can be claimed as input
    # credit; a line can override it (Product.itc_eligibility)
    itc_eligibility = models.CharField(max_length=10, default='eligible', choices=ITC_CHOICES)
    customer_notes = models.TextField(blank=True, default='')
    terms = models.TextField(blank=True, default='')

    INVOICE_TYPE_CHOICES = [
        ('sales', 'Sales'),
        ('purchase', 'Purchase'),
    ]
    invoice_type = models.CharField(max_length=10, choices=INVOICE_TYPE_CHOICES, default='sales')

    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
    ]
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid', db_index=True)

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('upi', 'UPI'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('card', 'Card'),
        ('other', 'Other'),
    ]
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True)


    class Meta(SoftDeleteModel.Meta):
        indexes = [
            models.Index(fields=['user', 'invoice_type', '-date', '-id'], name='inv_user_type_date_live', condition=models.Q(is_deleted=False)),
            models.Index(fields=['user', 'payment_status', '-date'], name='inv_user_status_date_live', condition=models.Q(is_deleted=False)),
            models.Index(fields=['receiver', '-date'], name='inv_receiver_date_live', condition=models.Q(is_deleted=False)),
            models.Index(fields=['vendor', '-date'], name='inv_vendor_date_live', condition=models.Q(is_deleted=False)),
        ]

    def __str__(self):
        return str(self.id)+str(self.user)

    def save(self, *args, **kwargs):
        if not self.date:
            self.date = timezone.now().date()
        super().save(*args, **kwargs)
TAX_CATEGORY_CHOICES = [
    ('taxable', 'Taxable'),
    ('nil', 'Nil-rated'),
    ('exempt', 'Exempt'),
    ('non_gst', 'Non-GST supply'),
]


class Product(models.Model):
    # Who created the line item. Tenant scoping goes through this (via the
    # company of the creator, the same rule as invoices) because a line item
    # is created before it is attached to an invoice. Null only on rows that
    # were never attached to an invoice before this field existed.
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='+')
    product_properties = models.ManyToManyField('Product_properties')  # connect to Product_property model
    gst_amount = models.DecimalField(max_digits=20,decimal_places=2)
    total_amount = models.DecimalField(max_digits=20,decimal_places=2)
    # For a 0% line: nil-rated, exempt or non-GST (GSTR-1 Table 8 columns).
    # A 0% "taxable" line is nil-rated, which is what a 0% rate means.
    tax_category = models.CharField(max_length=10, default='taxable', choices=TAX_CATEGORY_CHOICES)
    # purchase lines: overrides the invoice's ITC eligibility; blank = follow it
    itc_eligibility = models.CharField(max_length=10, blank=True, default='', choices=ITC_CHOICES)
    image = models.ForeignKey('ProductImage', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='line_items')

    def __str__(self):
        return str(self.total_amount)


class Product_properties(models.Model):
    new_product_in_frontend = models.ForeignKey('new_product_in_frontend',
                                                on_delete=models.CASCADE)  # connect to new_product_in_frontend model
    value = models.CharField(max_length=200,blank=True,null=True)


class new_product_in_frontend(SoftDeleteModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    input_title = models.CharField(max_length=30, blank=True)
    size = models.DecimalField(max_digits=20,decimal_places=2)
    is_show = models.BooleanField(default=False)
    is_calculable = models.BooleanField(default=False)  # if true then make formula in table
    formula = models.CharField(max_length=20, blank=True)
    on_with_out_gst_amount = models.BooleanField(default=False)
    presets = models.TextField(blank=True, null=True, help_text="Comma-separated preset values")
    show_calculated_value= models.BooleanField(default=False)
    default_value = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.input_title


class Font(models.Model):
    font = models.FileField(upload_to="fonts/")
    name = models.CharField(max_length=200,blank=True)

    def save(self, *args, **kwargs):
        if not self.name and self.font:
            self.name = os.path.splitext(os.path.basename(self.font.name))[0]

        super().save(*args, **kwargs)

class InvoiceExtractionLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(upload_to="invoices/logs/", max_length=255)
    response_data = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    invoice_type = models.CharField(max_length=50, blank=True, null=True)
    job_id = models.UUIDField(null=True, blank=True)
    meta_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['job_id'], name='extlog_job_idx'),
        ]


class ProductImage(SoftDeleteModel):
    """Reusable per-company image library for invoice line items. Any
    company member can upload one and any company member can attach it to a
    line item, the same shared-by-company convention as company_logo /
    new_product_in_frontend."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='product_images')
    company = models.ForeignKey('accounts.UserCompanies', on_delete=models.CASCADE,
                                null=True, blank=True, related_name='product_images')
    image = models.ImageField(upload_to='line_item_images/%Y/%m/')
    original_filename = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.company and self.user and getattr(self.user, 'user_company', None):
            self.company = self.user.user_company
        if not self.original_filename and self.image:
            self.original_filename = os.path.basename(self.image.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.original_filename or str(self.id)


class CustomField(SoftDeleteModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='custom_fields')
    company = models.ForeignKey('accounts.UserCompanies', on_delete=models.CASCADE, null=True, blank=True, related_name='custom_fields')
    name = models.CharField(max_length=100)
    
    FIELD_TYPE_CHOICES = [
        ('text', 'Text'),
        ('number', 'Number'),
        ('select', 'Select'),
        ('multiselect', 'Multi-Select'),
        ('date', 'Date'),
    ]
    field_type = models.CharField(max_length=20, choices=FIELD_TYPE_CHOICES, default='text')
    
    hidden = models.BooleanField(default=False)
    default_value = models.CharField(max_length=255, blank=True, null=True)
    multioption_value = models.JSONField(blank=True, null=True, help_text="List of choices/options for select or multiselect fields")
    
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.company and hasattr(self, 'user') and self.user and hasattr(self.user, 'user_company') and self.user.user_company:
            self.company = self.user.user_company
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.company.company_name if self.company else self.user.username})"

class Payment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey('accounts.UserCompanies', on_delete=models.CASCADE, null=True, blank=True)
    
    PAYMENT_TYPE_CHOICES = [
        ('received', 'Received'),
        ('made', 'Made')
    ]
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='received')
    
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    date = models.DateField(default=timezone.now)
    
    payment_method = models.CharField(
        max_length=20, choices=Invoice.PAYMENT_METHOD_CHOICES, blank=True, null=True)
        
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    
    customer = models.ForeignKey('companies.Customers', on_delete=models.CASCADE, blank=True, null=True)
    vendor = models.ForeignKey('companies.Vendor', on_delete=models.CASCADE, blank=True, null=True)
    invoice = models.ForeignKey('Invoice', on_delete=models.SET_NULL, blank=True, null=True, related_name='payments')
    
    created_at = models.DateTimeField(auto_now_add=True)
    

    class Meta:
        indexes = [
            models.Index(fields=['company', '-date'], name='pay_company_date_idx'),
        ]

    def save(self, *args, **kwargs):
        if not self.company and hasattr(self, 'user') and self.user and hasattr(self.user, 'user_company') and self.user.user_company:
            self.company = self.user.user_company
        super().save(*args, **kwargs)

class CreditDebitNote(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey('accounts.UserCompanies', on_delete=models.CASCADE, null=True, blank=True)
    
    NOTE_TYPE_CHOICES = [
        ('credit', 'Credit Note'),
        ('debit', 'Debit Note')
    ]
    note_type = models.CharField(max_length=20, choices=NOTE_TYPE_CHOICES, default='credit')
    note_number = models.CharField(max_length=50, blank=True, null=True)
    
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    # The GST included in `amount`. Null on notes recorded before this existed
    # (or without it): the GST report then can't net the note into the
    # liability and says so, rather than guessing a rate.
    gst_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text="GST included in the amount")
    date = models.DateField(default=timezone.now)
    reason = models.TextField(blank=True, null=True)
    
    customer = models.ForeignKey('companies.Customers', on_delete=models.CASCADE, blank=True, null=True)
    vendor = models.ForeignKey('companies.Vendor', on_delete=models.CASCADE, blank=True, null=True)
    invoice = models.ForeignKey('Invoice', on_delete=models.SET_NULL, blank=True, null=True, related_name='notes')
    
    created_at = models.DateTimeField(auto_now_add=True)
    

    class Meta:
        indexes = [
            models.Index(fields=['company', '-date'], name='note_company_date_idx'),
            models.Index(fields=['customer', '-date'], name='note_customer_date_idx'),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.gst_amount is not None and (self.gst_amount < 0 or self.gst_amount > (self.amount or 0)):
            raise ValidationError({'gst_amount': 'GST must be between 0 and the note amount.'})

    def save(self, *args, **kwargs):
        if not self.company and hasattr(self, 'user') and self.user and hasattr(self.user, 'user_company') and self.user.user_company:
            self.company = self.user.user_company
        super().save(*args, **kwargs)



class InvoiceHeaderConfig(models.Model):
    """Which optional header fields a company shows, and the defaults filled
    into new invoices. See invoice.header_config for the shape and rules.

    One row per company, created on first save: an untouched company reads as
    "everything shown, no defaults", exactly as before this existed.
    """
    company = models.OneToOneField('accounts.UserCompanies', on_delete=models.CASCADE,
                                   related_name='invoice_header_config')
    # {field_key: {"visible": bool, "use_default": bool, "default": value}}
    fields = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Invoice header settings'
        verbose_name_plural = 'Invoice header settings'

    def __str__(self):
        return 'Invoice header settings for %s' % self.company


class CompanyInvoiceNumbering(models.Model):
    """Per-company auto-numbering settings and running counter.

    A separate one-to-one table rather than columns on UserCompanies: that row
    is read by the tenant middleware on essentially every request, and a hot
    per-invoice counter does not belong on it.

    Sales and purchase invoices share this single counter; only sales invoices
    draw from it (see InvoiceView.post).
    """
    DEFAULT_TEMPLATE = numbering.DEFAULT_TEMPLATE
    RESET_CHOICES = numbering.RESET_CHOICES

    company = models.OneToOneField('accounts.UserCompanies', on_delete=models.CASCADE,
                                   related_name='invoice_numbering')
    enabled = models.BooleanField(default=False)
    template = models.CharField(max_length=60, default=DEFAULT_TEMPLATE)
    reset_period = models.CharField(max_length=10, choices=RESET_CHOICES, default='never')
    # The value that will be used NEXT, not the last one issued.
    next_number = models.PositiveIntegerField(default=1)
    # The period the counter is currently counting inside ('', '2026-08',
    # '2026', 'FY2026'). Recomputed from the clock on every generation, so
    # year rollover needs no cron.
    period_key = models.CharField(max_length=16, blank=True, default='')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Invoice numbering settings'
        verbose_name_plural = 'Invoice numbering settings'

    def __str__(self):
        return '%s -> %s (next %s)' % (self.company, self.template, self.next_number)


class EwayBill(models.Model):
    """The e-way bill for moving the goods on one invoice (rule 138, CGST Rules).

    Holds what the e-way bill portal asks for that an invoice doesn't carry:
    Part A extras (sub-type, document type, a ship-to address when the goods
    go somewhere other than the billing address, distance) and Part B
    (transport). Phase A has no API access: the details go into a bulk-upload
    JSON (invoice.eway), the user uploads it on the portal and types the EWB
    number back here. Rules and the file format live in invoice/eway.py.
    """
    SUPPLY_TYPE_CHOICES = [('O', 'Outward'), ('I', 'Inward')]
    # portal codes; only the ones an invoice can back are offered
    SUB_SUPPLY_CHOICES = [(1, 'Supply'), (3, 'Export'), (9, 'SKD/CKD/Lots')]
    DOC_TYPE_CHOICES = [('INV', 'Tax invoice'), ('BIL', 'Bill of supply')]
    MODE_CHOICES = [(1, 'Road'), (2, 'Rail'), (3, 'Air'), (4, 'Ship')]
    VEHICLE_TYPE_CHOICES = [('R', 'Regular'), ('O', 'Over-dimensional cargo')]
    STATUS_CHOICES = [('draft', 'Draft'), ('generated', 'Generated'), ('cancelled', 'Cancelled')]
    SOURCE_CHOICES = [('manual', 'Entered by hand'), ('api', 'E-way bill API')]

    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name='eway_bill')

    # Part A extras
    supply_type = models.CharField(max_length=1, default='O', choices=SUPPLY_TYPE_CHOICES)
    sub_supply_type = models.PositiveSmallIntegerField(default=1, choices=SUB_SUPPLY_CHOICES)
    doc_type = models.CharField(max_length=3, default='INV', choices=DOC_TYPE_CHOICES)
    # Ship-to: blank means the goods go to the customer's own address. Filled,
    # the e-way bill is "bill to - ship to" (transaction type 2). For an export
    # it is the port / airport the goods leave from.
    ship_to_name = models.CharField(max_length=100, blank=True, default='')
    ship_to_address = models.CharField(max_length=240, blank=True, default='')
    ship_to_place = models.CharField(max_length=50, blank=True, default='')
    ship_to_state_code = models.PositiveSmallIntegerField(null=True, blank=True)
    ship_to_pincode = models.CharField(max_length=6, blank=True, default='')
    # 0 = let the portal work out the PIN-to-PIN distance
    distance_km = models.PositiveIntegerField(default=0)

    # Part B
    transport_mode = models.PositiveSmallIntegerField(default=1, choices=MODE_CHOICES)
    vehicle_number = models.CharField(max_length=20, blank=True, default='')
    vehicle_type = models.CharField(max_length=1, default='R', choices=VEHICLE_TYPE_CHOICES)
    transporter_id = models.CharField(max_length=15, blank=True, default='',
                                      help_text='Transporter GSTIN or TRANSIN')
    transporter_name = models.CharField(max_length=100, blank=True, default='')
    transport_doc_number = models.CharField(max_length=15, blank=True, default='')
    transport_doc_date = models.DateField(null=True, blank=True)

    # result from the portal
    ewb_number = models.CharField(max_length=12, blank=True, default='')
    ewb_date = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, default='draft', choices=STATUS_CHOICES)
    source = models.CharField(max_length=10, default='manual', choices=SOURCE_CHOICES)
    raw = models.JSONField(null=True, blank=True)

    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'EWB {self.ewb_number or "draft"} for invoice {self.invoice_id}'
