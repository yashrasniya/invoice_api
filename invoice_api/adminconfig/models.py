from django.db import models

# Create your models here.
class Xl_download_config(models.Model):
    model = models.CharField(max_length=50)
    array = models.TextField(max_length=50000)

    def __str__(self):
        return self.model