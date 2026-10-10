"""Load a bundle written by `export_global_templates`.

    python manage.py import_global_templates [--file PATH] [--owner USERNAME] [--dry-run]

Matches existing global templates by name and updates them in place; templates
not found are created, published. Copies users already made from the gallery
are separate rows and are never touched.
"""
import base64
import json
import os
import uuid

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from yaml_manager.models import Yaml, YamlVersion

DEFAULT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'global_templates.json')


class Command(BaseCommand):
    help = "Create or update global gallery templates from a JSON bundle."

    def add_arguments(self, parser):
        parser.add_argument('--file', default=DEFAULT_FILE)
        parser.add_argument('--owner', help="Username that owns newly created templates (default: first superuser).")
        parser.add_argument('--dry-run', action='store_true', help="Show what would change and write nothing.")

    def handle(self, *args, **opts):
        path = os.path.normpath(opts['file'])
        try:
            with open(path) as f:
                bundle = json.load(f)
        except (OSError, ValueError) as e:
            raise CommandError(f"Cannot read bundle {path}: {e}")

        if opts['owner']:
            owner = User.objects.filter(username=opts['owner']).first()
        else:
            owner = User.objects.filter(is_superuser=True).order_by('id').first()
        if owner is None:
            raise CommandError("No owner user found; pass --owner USERNAME.")

        dry = opts['dry_run']
        created = updated = 0
        with transaction.atomic():
            for t in bundle:
                existing = Yaml.objects.filter(is_global=True, template_name=t['template_name']).order_by('id')
                y = existing.first()
                if existing.count() > 1:
                    self.stdout.write(self.style.WARNING(
                        f"  {t['template_name']}: {existing.count()} globals share this name; updating id {y.id}"))
                verb = 'update' if y else 'create'
                self.stdout.write(f"{'[dry-run] ' if dry else ''}{verb}: {t['template_name']}")
                if dry:
                    continue
                if y is None:
                    y = Yaml(user=owner, is_default=False)
                    created += 1
                else:
                    updated += 1
                y.template_name = t['template_name']
                y.is_global = True
                y.is_published = True
                for k in ('global_category', 'description', 'is_html', 'page_size', 'version',
                          'auto_scale', 'auto_save', 'elements'):
                    setattr(y, k, t[k])
                y.save()
                y.yaml_file.save(f"{uuid.uuid4()}.html", ContentFile(t['html'].encode('utf-8')), save=False)
                if t.get('thumbnail_b64'):
                    y.pdf_template.save(f"{uuid.uuid4()}.jpg",
                                        ContentFile(base64.b64decode(t['thumbnail_b64'])), save=False)
                y.save()
                latest = y.versions.first()
                if latest is None or latest.version_data != t['html']:
                    YamlVersion.objects.create(yaml=y, version_data=t['html'])
        if dry:
            self.stdout.write("Dry run: nothing written.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Done: {created} created, {updated} updated."))
