from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager


# Create your models here.
class User_manager(BaseUserManager):
    def create_superuser(self, username, email='', password=None, **extra_fields):

        if not username:
            raise ValueError("User must have an email")
        if not password:
            raise ValueError("User must have a password")
        user = self.model(
            username=username
        )
        user.set_password(password)

        user.email = email

        user.is_admin = True
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save(using=self._db)
        return user
    def create_user(self, username, email='', password=None, **extra_fields):
        if not username:
            raise ValueError("User must have an email")
        if not password:
            raise ValueError("User must have a password")
        user = self.model(
            username=username
        )
        user.set_password(password)

        user.email = email


        user.is_active = True
        user.save(using=self._db)
        return user

class User(AbstractUser):
    gender = models.CharField(max_length=20, choices=(('Male', 'Male'), ('Female', 'Female')),blank=True)
    dob = models.DateField(null=True,blank=True)
    objects = User_manager()
    mobile_number = models.CharField(max_length=12,blank=True)
    profile = models.FileField(upload_to='accounts/profile/',null=True,blank=True)

    company_name = models.CharField(max_length=30, blank=True, null=True)
    company_address = models.CharField(max_length=30, blank=True, null=True)
    company_gst_number = models.CharField(max_length=30, blank=True, null=True)
    state = models.CharField(max_length=30, blank=True, null=True)
    state_code = models.IntegerField(null=True, blank=True)
    company_email_id = models.EmailField(max_length=30, blank=True, null=True)
    company_logo = models.ImageField(upload_to='accounts')
    bank_name = models.CharField(max_length=30, blank=True, null=True)
    account_number = models.CharField(max_length=30, blank=True, null=True)
    branch = models.CharField(max_length=30, blank=True, null=True)
    ifsc_code = models.CharField(max_length=30, blank=True, null=True)
    def __str__(self):
        return self.name()

    def name(self):
        return str(self.first_name+' '+self.last_name).title()


class Superuser(User):
    class Meta:
        verbose_name = 'Superuser'
        verbose_name_plural = 'Superusers'
        proxy = True
class CR(User):
    class Meta:
        verbose_name = 'CR'
        verbose_name_plural = 'CRs'
        proxy = True
