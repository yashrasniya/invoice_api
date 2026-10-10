"""Write every published global template to a JSON bundle.

    python manage.py export_global_templates [--output PATH]

The bundle carries each template's HTML, editor blocks, metadata and
thumbnail (base64), so it can be loaded on another environment with
`import_global_templates`.
"""
import base64
import json
import os

from django.core.management.base import BaseCommand

from yaml_manager.models import Yaml

DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'global_templates.json')


def _read(field):
    if not field:
        return None
    field.file.seek(0)
    return field.file.read()


class Command(BaseCommand):
    help = "Export published global templates to a JSON bundle."

    def add_arguments(self, parser):
        parser.add_argument('--output', default=DEFAULT_OUTPUT)

    def handle(self, *args, **opts):
        out = []
        for y in Yaml.objects.filter(is_global=True, is_published=True).order_by('id'):
            version = y.versions.first()
            html = version.version_data if version else None
            if not html:
                raw = _read(y.yaml_file)
                html = raw.decode('utf-8') if raw else ''
            thumb = _read(y.pdf_template)
            out.append({
                'template_name': y.template_name,
                'global_category': y.global_category,
                'description': y.description,
                'is_html': y.is_html,
                'page_size': y.page_size,
                'version': y.version,
                'auto_scale': y.auto_scale,
                'auto_save': y.auto_save,
                'elements': y.elements,
                'html': html,
                'thumbnail_b64': base64.b64encode(thumb).decode('ascii') if thumb else None,
            })
        path = os.path.normpath(opts['output'])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        self.stdout.write(f"Exported {len(out)} templates to {path}")
