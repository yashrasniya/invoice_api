from django.db import models

# Create your models here.

class BillShare(models.Model):
    user = models.ForeignKey('accounts.User',on_delete=models.CASCADE)
    invoice = models.ForeignKey('invoice.Invoice',on_delete=models.CASCADE)
    to = models.CharField(max_length=300,blank=True,null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    type = models.CharField(choices=(('whatsapp','whatsapp'),),max_length=30,default='whatsapp')
