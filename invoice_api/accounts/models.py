import secrets

from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager

from invoice_api.softdelete import SoftDeleteModel


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
    user_company = models.ForeignKey('UserCompanies',on_delete=models.CASCADE,null=True)
    is_company_admin = models.BooleanField(default=False)

    def __str__(self):
        return self.name()

    def is_company_varified(self):
        if self.user_company:
            return self.user_company.is_varified
        return False

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

class UserCompanies(models.Model):
    is_varified = models.BooleanField(default=False)
    company_name = models.CharField(max_length=30, blank=True, null=True)
    company_address = models.CharField(max_length=30, blank=True, null=True)
    company_gst_number = models.CharField(max_length=30, blank=True, null=True)
    state = models.CharField(max_length=30, blank=True, null=True)
    state_code = models.IntegerField(null=True, blank=True)
    company_email_id = models.EmailField(max_length=30, blank=True, null=True)
    company_logo = models.ImageField(upload_to='accounts',null=True,blank=True)
    bank_name = models.CharField(max_length=30, blank=True, null=True)
    account_number = models.CharField(max_length=30, blank=True, null=True)
    branch = models.CharField(max_length=30, blank=True, null=True)
    ifsc_code = models.CharField(max_length=30, blank=True, null=True)

    # UPI collection: the VPA is stored regardless, but the QR only reaches
    # invoices once the company opts in, so a saved id can be kept on file
    # without every exported bill suddenly showing a payment code.
    upi_id = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="UPI id / VPA to collect payments on, e.g. acme@okaxis")
    show_upi_qr = models.BooleanField(
        default=False,
        help_text="Print a UPI QR for the invoice total on exported invoices")

    subscriptions_plan = models.ForeignKey('Subscriptions',on_delete=models.CASCADE,null=True,blank=True)

    def upi_payment_link(self, amount, note=None):
        """UPI deep link for `amount`, or None when this company has no QR."""
        from upi_qr import company_upi_link
        return company_upi_link(self, amount, note=note)

    def logo_scaled_height(self, desired_width):
        if self.company_logo and getattr(self.company_logo, 'width', None) and getattr(self.company_logo, 'height', None):
            return int((self.company_logo.height / self.company_logo.width) * desired_width)
        return int(desired_width)

    def __str__(self):
        return self.company_name

class Subscriptions(models.Model):
    name = models.CharField(max_length=255,null=True)


# ---------------------------------------------------------------------------
# Multi-tenant authorization: permissions, roles, groups, direct grants, audit
# ---------------------------------------------------------------------------

class CompanyPermission(models.Model):
    TYPE_CHOICES = [('MODEL', 'Model Permission'), ('CUSTOM', 'Custom Business Permission')]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, db_index=True)
    description = models.TextField(blank=True)
    permission_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='CUSTOM')
    # company=NULL → system-wide permission (Product Owner managed)
    company = models.ForeignKey(
        'UserCompanies', on_delete=models.CASCADE, null=True, blank=True,
        related_name='custom_permissions')
    is_system_permission = models.BooleanField(default=False)  # editable only by Product Owner

    class Meta:
        unique_together = ('code', 'company')
        constraints = [
            # unique_together does NOT deduplicate rows with company=NULL in SQL
            models.UniqueConstraint(
                fields=['code'],
                condition=models.Q(company__isnull=True),
                name='uniq_system_perm_code',
            )
        ]

    def __str__(self):
        return self.code


class CompanyRole(SoftDeleteModel):
    # company=NULL → global system role (e.g. Product Owner)
    company = models.ForeignKey(
        'UserCompanies', on_delete=models.CASCADE, null=True, blank=True,
        related_name='roles')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_system_role = models.BooleanField(default=False)
    permissions = models.ManyToManyField(CompanyPermission, related_name='roles', blank=True)
    users = models.ManyToManyField('User', related_name='roles', blank=True)

    class Meta:
        base_manager_name = 'all_objects'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'name'],
                condition=models.Q(is_deleted=False),
                name='uniq_role_name_per_company',
            ),
            models.UniqueConstraint(
                fields=['name'],
                condition=models.Q(company__isnull=True, is_deleted=False),
                name='uniq_global_role_name',
            )
        ]

    def delete(self, *args, **kwargs):
        # a deleted role must stop granting anything immediately
        self.users.clear()
        self.permissions.clear()
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.company or 'global'})"


class CompanyGroup(SoftDeleteModel):
    company = models.ForeignKey(
        'UserCompanies', on_delete=models.CASCADE, related_name='custom_groups')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    users = models.ManyToManyField('User', related_name='company_groups', blank=True)
    roles = models.ManyToManyField(CompanyRole, related_name='company_groups', blank=True)
    permissions = models.ManyToManyField(
        CompanyPermission, related_name='company_groups', blank=True)

    class Meta:
        base_manager_name = 'all_objects'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'name'],
                condition=models.Q(is_deleted=False),
                name='uniq_group_name_per_company',
            )
        ]

    def delete(self, *args, **kwargs):
        # a deleted group must stop granting anything immediately
        self.users.clear()
        self.roles.clear()
        self.permissions.clear()
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.company})"


class UserDirectPermission(models.Model):
    user = models.ForeignKey(
        'User', on_delete=models.CASCADE, related_name='user_direct_permissions')
    permission = models.ForeignKey(
        CompanyPermission, on_delete=models.CASCADE, related_name='direct_users')
    company = models.ForeignKey(
        'UserCompanies', on_delete=models.CASCADE, related_name='direct_user_permissions')
    is_granted = models.BooleanField(default=True)  # False = explicit DENY, overrides role/group grants
    granted_by = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, related_name='+')  # accountability
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'permission', 'company')

    def __str__(self):
        sign = '+' if self.is_granted else '-'
        return f"{sign}{self.permission.code} → {self.user}"


class UserInvite(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('revoked', 'Revoked'),
        ('expired', 'Expired'),
    ]
    EXPIRY_DAYS = 7

    company = models.ForeignKey(
        'UserCompanies', on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField()
    role = models.ForeignKey(
        CompanyRole, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invites', help_text="Role assigned on accept (default: Member)")
    invited_by = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, related_name='sent_invites')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    accepted_user = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # one live invite per email per company
            models.UniqueConstraint(
                fields=['company', 'email'],
                condition=models.Q(status='pending'),
                name='one_pending_invite_per_email_per_company',
            )
        ]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            from datetime import timedelta
            from django.utils import timezone
            self.expires_at = timezone.now() + timedelta(days=self.EXPIRY_DAYS)
        super().save(*args, **kwargs)

    def is_valid(self):
        from django.utils import timezone
        return self.status == 'pending' and timezone.now() <= self.expires_at

    def __str__(self):
        return f"{self.email} → {self.company} ({self.status})"


class AuditLog(models.Model):
    company = models.ForeignKey(
        'UserCompanies', on_delete=models.CASCADE, related_name='audit_logs',
        null=True, blank=True)
    user = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_actions')
    action = models.CharField(max_length=50)           # CREATE, UPDATE, DELETE, ASSIGN, REVOKE, DENY
    resource_type = models.CharField(max_length=100)   # ROLE, PERMISSION, GROUP, SUBSCRIPTION, PLAN
    resource_id = models.CharField(max_length=255, blank=True, null=True)
    previous_data = models.JSONField(null=True, blank=True)  # populated via pre_save snapshot
    new_data = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['company', 'resource_type', '-timestamp'])]

    # append-only
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("AuditLog is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog entries cannot be deleted")


class ServiceToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    token = models.CharField(max_length=128, unique=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(32)

        super().save(*args, **kwargs)


class SocialAccount(models.Model):
    PROVIDER_CHOICES = [('google', 'Google')]

    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='social_accounts')
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, default='google')
    provider_uid = models.CharField(max_length=255)   # Google's stable 'sub' claim — NOT email
    email = models.EmailField(blank=True)              # email at time of linking (informational)
    picture_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('provider', 'provider_uid')