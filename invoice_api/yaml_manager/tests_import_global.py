import json
import os
import tempfile

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from yaml_manager.models import Yaml

BUNDLE = [{
    'template_name': 'Imported One', 'global_category': 'GST', 'description': 'd',
    'is_html': True, 'page_size': 'A4', 'version': '1.0', 'auto_scale': False, 'auto_save': True,
    'elements': [{'id': '1', 'type': 'text', 'content': 'hi', 'x': 1, 'y': 1}],
    'html': '<html><body>v1</body></html>', 'thumbnail_b64': None,
}]


class ImportGlobalTemplatesTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(username='root', email='r@x.com', password='x')
        fd, self.path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.remove, self.path)

    def _run(self, bundle, *flags):
        with open(self.path, 'w') as f:
            json.dump(bundle, f)
        call_command('import_global_templates', '--file', self.path, *flags, verbosity=0)

    def test_creates_published_global_then_updates_in_place(self):
        self._run(BUNDLE)
        y = Yaml.objects.get(template_name='Imported One')
        self.assertTrue(y.is_global and y.is_published)
        self.assertEqual(y.versions.first().version_data, '<html><body>v1</body></html>')

        self._run([dict(BUNDLE[0], html='<html><body>v2</body></html>')])
        self.assertEqual(Yaml.objects.filter(template_name='Imported One').count(), 1)
        y.refresh_from_db()
        self.assertEqual(y.versions.first().version_data, '<html><body>v2</body></html>')

    def test_dry_run_writes_nothing(self):
        self._run(BUNDLE, '--dry-run')
        self.assertFalse(Yaml.objects.exists())
