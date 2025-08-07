import os
from io import BytesIO

from django.db import models
from pdf2image import convert_from_bytes
from django.core.files import File

from accounts.models import User
from utilitis import pdf_to_jpg


# Create your models here.


class Yaml(models.Model):
    yaml_file=models.FileField(upload_to="yaml")
    pdf_template=models.FileField(upload_to="pdf_template")
    user=models.ForeignKey(User,on_delete=models.CASCADE)

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        # Save the uploaded PDF file first
        super().save(force_insert, force_update, using, update_fields)

        # Only convert if it's a PDF file
        if self.pdf_template.name.endswith('.pdf'):
            # Absolute path to original PDF
            pdf_path = self.pdf_template.path

            # Read bytes from PDF
            with open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()

            # Convert PDF to list of image(s)
            images = convert_from_bytes(pdf_bytes, dpi=300)

            # Pick the first page and convert to in-memory JPG
            first_image = images[0]
            img_io = BytesIO()
            first_image.save(img_io, format='JPEG')
            img_io.seek(0)

            # Generate JPG filename
            jpg_filename = os.path.splitext(os.path.basename(self.pdf_template.name))[0] + '_page_1.jpg'
            jpg_relative_path = os.path.join('pdf_templates/', jpg_filename)  # same as upload_to

            # Save JPG to the same FileField, replacing the original PDF
            self.pdf_template.save(jpg_relative_path, File(img_io), save=False)

            # Remove original PDF file
            os.remove(pdf_path)

            # Save again to update DB
            super().save(force_insert, force_update, using, update_fields)

            print(f"Replaced PDF with JPG: {self.pdf_template.name}")
