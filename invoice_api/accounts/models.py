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


class User(AbstractUser):
    gender = models.CharField(max_length=20, choices=(('Male', 'Male'), ('Female', 'Female')),blank=True)
    dob = models.DateField(null=True,blank=True)
    objects = User_manager()
    mobile_number = models.CharField(max_length=12,blank=True)
    profile = models.FileField(upload_to='accounts/profile/',null=True,blank=True)

    def __str__(self):
        return self.name()

    def name(self):
        return self.first_name+' '+self.last_name


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
