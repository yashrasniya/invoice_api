from django.core.files.base import ContentFile
from rest_framework.test import APITestCase

from accounts.models import User
from yaml_manager.models import Yaml, YamlVersion


class OnboardingTemplateTests(APITestCase):
    URL = '/api/yaml/onboarding/'

    def setUp(self):
        self.user = User.objects.create_user(username='new', password='pw-12345-x', email='n@x.com')
        starter = Yaml(user=self.user, is_default=True)
        starter.yaml_file.save('starter.yaml', ContentFile(b'Bill: {}'), save=True)
        self.starter = starter

        admin = User.objects.create_user(username='admin', password='pw-12345-x', email='a@x.com')
        self.global_t = Yaml(user=admin, template_name='Retail', is_global=True, is_published=True)
        self.global_t.yaml_file.save('g.yaml', ContentFile(b'Bill: {a: 1}'), save=True)
        YamlVersion.objects.create(yaml=self.global_t, version_data='Bill: {a: 1}')
        self.draft = Yaml(user=admin, template_name='Draft', is_global=True, is_published=False)
        self.draft.yaml_file.save('d.yaml', ContentFile(b'x: 1'), save=True)
        self.client.force_authenticate(self.user)

    def test_get_lists_default_and_published_globals_only(self):
        data = self.client.get(self.URL).json()
        self.assertEqual(data['default_template']['id'], self.starter.id)
        self.assertEqual([t['id'] for t in data['global_templates']], [self.global_t.id])

    def test_select_global_replaces_default(self):
        r = self.client.post(self.URL, {'template_id': self.global_t.id}, format='json')
        self.assertEqual(r.status_code, 201)
        chosen = Yaml.objects.get(id=r.json()['id'])
        self.assertTrue(chosen.is_default)
        self.assertEqual(chosen.user, self.user)
        self.assertFalse(chosen.is_global)
        self.assertEqual(chosen.versions.count(), 1)
        self.assertEqual(Yaml.objects.filter(user=self.user, is_default=True).count(), 1)

    def test_unpublished_or_missing_template_rejected(self):
        for tid in (self.draft.id, 999999, None):
            r = self.client.post(self.URL, {'template_id': tid}, format='json')
            self.assertEqual(r.status_code, 404)
        self.starter.refresh_from_db()
        self.assertTrue(self.starter.is_default)


class GlobalTemplatePreviewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pw-12345-x', email='u@x.com')
        admin = User.objects.create_user(username='adm', password='pw-12345-x', email='a@x.com')

        def make(name, html, **kw):
            t = Yaml(user=admin, template_name=name, is_global=True, **kw)
            t.yaml_file.save('t.html' if kw.get('is_html') else 't.yaml', ContentFile(html.encode()), save=True)
            return t
        self.html = make('H', '<html><body><h1>{{ company.company_name }} {{ invoice.invoice_number }}</h1></body></html>',
                         is_published=True, is_html=True)
        self.yaml = make('Y', 'Bill: {}', is_published=True)
        self.draft = make('D', '<p>x</p>', is_published=False, is_html=True)
        self.client.force_authenticate(self.user)

    def test_html_template_renders_pdf(self):
        r = self.client.get(f'/api/yaml/gallery/{self.html.id}/preview/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(r.streaming_content).startswith(b'%PDF'))

    def test_yaml_unpublished_missing_are_404(self):
        for tid in (self.yaml.id, self.draft.id, 999999):
            self.assertEqual(self.client.get(f'/api/yaml/gallery/{tid}/preview/').status_code, 404)

    def test_requires_login(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(f'/api/yaml/gallery/{self.html.id}/preview/').status_code, (401, 403))

    def test_serializer_exposes_preview_url_for_html_only(self):
        data = {t['id']: t for t in self.client.get('/api/yaml/gallery/').json()}
        self.assertTrue(data[self.html.id]['preview_url'].endswith(f'/gallery/{self.html.id}/preview/'))
        self.assertIsNone(data[self.yaml.id]['preview_url'])


class GlobalTemplatePreviewPngTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u2', password='pw-12345-x', email='u2@x.com')
        admin = User.objects.create_user(username='adm2', password='pw-12345-x', email='a2@x.com')
        self.html = Yaml(user=admin, template_name='H', is_global=True, is_published=True, is_html=True)
        self.html.yaml_file.save('t.html', ContentFile(b'<html><body><h1>{{ company.company_name }}</h1></body></html>'), save=True)
        self.client.force_authenticate(self.user)

    def test_png_format_returns_a_png_image(self):
        r = self.client.get(f'/api/yaml/gallery/{self.html.id}/preview/?output=png')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertTrue(r.content.startswith(b'\x89PNG'))

    def test_default_is_still_pdf(self):
        r = self.client.get(f'/api/yaml/gallery/{self.html.id}/preview/')
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_png_for_missing_template_is_404(self):
        self.assertEqual(self.client.get('/api/yaml/gallery/999999/preview/?output=png').status_code, 404)
