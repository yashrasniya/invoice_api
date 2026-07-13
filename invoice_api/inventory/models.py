from django.core.exceptions import ValidationError
from django.db import models


class Category(models.Model):
    company = models.ForeignKey(
        'accounts.UserCompanies', on_delete=models.CASCADE,
        null=True, blank=True, related_name='inventory_categories')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Categories"
        constraints = [
            # unique per company, not globally
            models.UniqueConstraint(fields=['company', 'name'],
                                    name='uniq_category_per_company'),
        ]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    company = models.ForeignKey(
        'accounts.UserCompanies', on_delete=models.CASCADE,
        null=True, blank=True, related_name='inventory_suppliers')
    name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    company = models.ForeignKey(
        'accounts.UserCompanies', on_delete=models.CASCADE,
        null=True, blank=True, related_name='inventory_products')
    sku = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    # legacy standalone supplier — superseded by `vendor` (the same Vendor
    # records used on the Purchases page)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    vendor = models.ForeignKey('companies.Vendor', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_products')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=18.00)
    current_stock = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # SKU unique per company, not globally
            models.UniqueConstraint(fields=['company', 'sku'],
                                    name='uniq_sku_per_company'),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class StockMovement(models.Model):
    MOVEMENT_CHOICES = (
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements')
    quantity = models.IntegerField(help_text="Use positive numbers for IN and OUT. The system will adjust stock based on movement_type.")
    movement_type = models.CharField(max_length=3, choices=MOVEMENT_CHOICES)
    date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.movement_type} - {self.quantity} x {self.product.name}"

    def clean(self):
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be a positive number.'})

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # We only want to adjust stock on creation, skip on updates for safety
        if is_new:
            if self.movement_type == 'IN':
                self.product.current_stock += self.quantity
            elif self.movement_type == 'OUT':
                self.product.current_stock -= self.quantity
            self.product.save()

    def delete(self, *args, **kwargs):
        # reverse the stock adjustment so deleting a movement doesn't leave
        # phantom stock changes behind
        if self.movement_type == 'IN':
            self.product.current_stock -= self.quantity
        elif self.movement_type == 'OUT':
            self.product.current_stock += self.quantity
        self.product.save()
        super().delete(*args, **kwargs)
