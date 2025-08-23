import os
from django.core.management.base import BaseCommand
from django.core.files import File
from invoice.models import Font  # adjust app name if different

class Command(BaseCommand):
    help = "Import fonts from a local folder into the Font model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            help="Path to the folder containing fonts",
            required=True
        )

    def handle(self, *args, **options):
        folder_path = options["path"]

        if not os.path.exists(folder_path):
            self.stderr.write(self.style.ERROR(f"❌ Folder does not exist: {folder_path}"))
            return

        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)

            if not os.path.isfile(file_path):
                continue

            # check for font file extensions
            if not filename.lower().endswith((".ttf", ".otf", ".woff", ".woff2")):
                continue

            with open(file_path, "rb") as f:
                font_obj = Font()
                font_obj.font.save(filename, File(f), save=False)  # attach file
                font_obj.save()

            self.stdout.write(self.style.SUCCESS(f"✅ Imported: {filename}"))

