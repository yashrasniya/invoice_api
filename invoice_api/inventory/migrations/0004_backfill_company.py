"""
Backfill company on legacy inventory rows. Inventory previously had no
owner, so all companies shared one pool. Ownership is inferred from stock
movements' "Auto-deducted for Invoice #N" notes → invoice → company (the
company with the most references wins); fallback: the first company.
"""
import re
from collections import Counter

from django.db import migrations


def forwards(apps, schema_editor):
    Category = apps.get_model('inventory', 'Category')
    Supplier = apps.get_model('inventory', 'Supplier')
    Product = apps.get_model('inventory', 'Product')
    StockMovement = apps.get_model('inventory', 'StockMovement')
    Invoice = apps.get_model('invoice', 'Invoice')
    UserCompanies = apps.get_model('accounts', 'UserCompanies')

    # infer the owning company from movement notes
    counts = Counter()
    for movement in StockMovement.objects.all():
        match = re.search(r'Invoice #(\d+)', movement.notes or '')
        if match:
            invoice = (Invoice.objects
                       .filter(id=int(match.group(1)))
                       .select_related('user').first())
            if invoice and invoice.user and invoice.user.user_company_id:
                counts[invoice.user.user_company_id] += 1

    if counts:
        company_id = counts.most_common(1)[0][0]
    else:
        first = UserCompanies.objects.order_by('id').first()
        company_id = first.id if first else None

    if company_id is None:
        return

    Category.objects.filter(company__isnull=True).update(company_id=company_id)
    Supplier.objects.filter(company__isnull=True).update(company_id=company_id)
    Product.objects.filter(company__isnull=True).update(company_id=company_id)


def backwards(apps, schema_editor):
    pass  # nothing sensible to undo


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_category_company_product_company_supplier_company_and_more'),
        ('invoice', '0020_invoice_payment_method_invoice_payment_status'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
