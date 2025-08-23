from django.db import models
from accounts.models import User


class Customers(models.Model):
    # Basic Info
    name = models.CharField(max_length=255, default="Unnamed Company")
    legal_name = models.CharField(max_length=255, blank=True, default="", help_text="As per GST/PAN records")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # Contact
    email = models.EmailField(max_length=255, blank=True, null=True, default=None)
    phone_number = models.CharField(max_length=15, blank=True, null=True, default=None)
    website = models.URLField(blank=True, null=True, default=None)

    # Address
    address = models.CharField(max_length=3000, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    district = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    state_code = models.IntegerField(blank=True, null=True, default=None, help_text="GST State Code")
    pincode = models.CharField(max_length=10, blank=True, default="")

    # Govt Identifiers
    gst_number = models.CharField(max_length=15, blank=True, default="", help_text="GSTIN (15 characters)")
    pan_number = models.CharField(max_length=10, blank=True, default="")

    # Banking Details
    bank_name = models.CharField(max_length=100, blank=True, default="")
    account_number = models.CharField(max_length=30, blank=True, default="")
    ifsc_code = models.CharField(max_length=11, blank=True, default="")
    branch = models.CharField(max_length=100, blank=True, default="")

    # Misc
    incorporation_date = models.DateField(blank=True, null=True, default=None)
    business_type = models.CharField(
        max_length=50,
        choices=[
            ("private_limited", "Private Limited"),
            ("public_limited", "Public Limited"),
            ("partnership", "Partnership"),
            ("sole_prop", "Sole Proprietorship"),
            ("llp", "LLP"),
            ("ngo", "NGO"),
            ("other", "Other"),
        ],
        default="sole_prop",
    )
    logo = models.ImageField(upload_to="company_logos/", blank=True, null=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or "Unnamed Company"

