"""
Link inventory to the purchase vendors: for every product with a legacy
Supplier, find or create a companies.Vendor with the same name in the
product's company and point product.vendor at it. Supplier contact info is
carried over onto newly created vendors.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    Vendor = apps.get_model('companies', 'Vendor')
    User = apps.get_model('accounts', 'User')

    for product in Product.objects.filter(supplier__isnull=False):
        supplier = product.supplier
        company = product.company
        if company is None:
            continue
        vendor = Vendor.objects.filter(
            user__user_company=company, name=supplier.name).first()
        if vendor is None:
            owner = (User.objects.filter(user_company=company,
                                         is_company_admin=True)
                     .order_by('id').first() or
                     User.objects.filter(user_company=company)
                     .order_by('id').first())
            if owner is None:
                continue
            vendor = Vendor.objects.create(
                user=owner,
                name=supplier.name,
                email=supplier.email or None,
                phone_number=(supplier.phone or '')[:15] or None,
                address=supplier.address or '',
            )
        product.vendor = vendor
        product.save(update_fields=['vendor'])


def backwards(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    Product.objects.update(vendor=None)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0005_product_vendor_alter_product_supplier'),
        ('companies', '0008_whatsapp_shared_number_feature'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
