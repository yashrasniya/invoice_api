from django.db import models
from accounts.models import User


class Invoice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=30,blank=True,null=True)
    receiver = models.ForeignKey('companies.Companies', on_delete=models.CASCADE,blank=True,null=True)
    date = models.DateField(null=True,blank=True)
    products = models.ManyToManyField('Product',blank=True,null=True)  # connect to Product model
    gst_final_amount = models.DecimalField(max_digits=20,decimal_places=2,null=True)
    total_final_amount = models.DecimalField(max_digits=20,decimal_places=2,null=True)

    def __str__(self):
        return str(self.id)+str(self.user)


class Product(models.Model):
    product_properties = models.ManyToManyField('Product_properties')  # connect to Product_property model
    gst_amount = models.DecimalField(max_digits=20,decimal_places=2)
    total_amount = models.DecimalField(max_digits=20,decimal_places=2)

    def __str__(self):
        return str(self.total_amount)


class Product_properties(models.Model):
    new_product_in_frontend = models.ForeignKey('new_product_in_frontend',
                                                on_delete=models.CASCADE)  # connect to new_product_in_frontend model
    value = models.CharField(max_length=20,blank=True,null=True)


class new_product_in_frontend(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    input_title = models.CharField(max_length=30, blank=True)
    size = models.DecimalField(max_digits=20,decimal_places=2)
    is_show = models.BooleanField(default=False)
    is_calculable = models.BooleanField(default=False)  # if true then make formula in table
    formula = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.input_title
