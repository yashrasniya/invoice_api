from django.db import models

from accounts.models import User


# Create your models here.


class Yaml(models.Model):
    yaml_file=models.FileField(upload_to="yaml")
    pdf_template=models.FileField(upload_to="pdf_template")
    user=models.ForeignKey(User,on_delete=models.CASCADE)
