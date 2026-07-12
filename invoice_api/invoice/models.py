import os
from datetime import datetime

from django.db import models
from django.utils import timezone

from accounts.models import User


class Invoice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=30,blank=True,null=True)
    receiver = models.ForeignKey('companies.Customers', on_delete=models.CASCADE,blank=True,null=True)
    vendor = models.ForeignKey('companies.Vendor', on_delete=models.CASCADE,blank=True,null=True)
    date = models.DateField(null=True,blank=True)
    products = models.ManyToManyField('Product',blank=True,null=True)  # connect to Product model
    gst_final_amount = models.DecimalField(max_digits=20,decimal_places=2,null=True)
    total_final_amount = models.DecimalField(max_digits=20,decimal_places=2,null=True)
    custom_header_field = models.JSONField(blank=True, null=True, default=dict)

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

    def __str__(self):
        return str(self.id)+str(self.user)

    def save(self, *args, **kwargs):
        if not self.date:
            self.date = timezone.now().date()
        super().save(*args, **kwargs)
class Product(models.Model):
    product_properties = models.ManyToManyField('Product_properties')  # connect to Product_property model
    gst_amount = models.DecimalField(max_digits=20,decimal_places=2)
    total_amount = models.DecimalField(max_digits=20,decimal_places=2)

    def __str__(self):
        return str(self.total_amount)


class Product_properties(models.Model):
    new_product_in_frontend = models.ForeignKey('new_product_in_frontend',
                                                on_delete=models.CASCADE)  # connect to new_product_in_frontend model
    value = models.CharField(max_length=200,blank=True,null=True)


class new_product_in_frontend(models.Model):
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
    file = models.FileField(upload_to="invoices/logs/")
    response_data = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    invoice_type = models.CharField(max_length=50, blank=True, null=True)
    job_id = models.UUIDField(null=True, blank=True)
    meta_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CustomField(models.Model):
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

