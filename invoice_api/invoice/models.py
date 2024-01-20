from django.db import models
from django.contrib.auth.models import User


class Invoice(models.Model):
    invoice_number = models.CharField(max_length=30)
    receiver = models.CharField(max_length=30, blank=True)
    date = models.DateField(auto_now=True)
    product = models.ManyToManyField('Product')  # connect to Product model
    gst_final_amount = models.DecimalField(max_digits=20)
    total_final_amount = models.DecimalField(max_digits=20)

    def __str__(self):
        return self.invoice_number


class Product(models.Model):
    title = models.CharField(max_length=30, blank=True)
    product_property = models.ManyToManyField('Product_property')  # connect to Product_property model
    gst_amount = models.DecimalField(max_digits=20)
    total_amount = models.DecimalField(max_digits=20)
    new_product_in_frontend = models.ForeignKey('new_product_in_frontend', on_delete=models.CASCADE)
    value = models.DecimalField(max_digits=20, decimal_places=2)

    def __str__(self):
        return self.title


class Product_property(models.Model):
    new_product_in_frontend = models.ForeignKey('new_product_in_frontend',
                                                on_delete=models.CASCADE)  # connect to new_product_in_frontend model
    value = models.DecimalField(max_digits=20)


class new_product_in_frontend(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    input_title = models.CharField(max_length=30, blank=True)
    size = models.DecimalField(max_digits=20)
    is_show = models.BooleanField()
    is_calculable = models.BooleanField()  # if true then make formula in table

    def __str__(self):
        return self.input_title
