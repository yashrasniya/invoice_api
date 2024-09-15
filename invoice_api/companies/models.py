from django.db import models
from accounts.models import User


# Create your models here.
class Companies(models.Model):
    name = models.CharField(max_length=20, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    address = models.CharField(max_length=30, blank=True)
    gst_number = models.CharField(max_length=30, blank=True)
    state = models.CharField(max_length=30, blank=True)
    state_code = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return self.name
