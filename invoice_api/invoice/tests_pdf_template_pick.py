from django.core.files.base import ContentFile
from django.test import TestCase

from accounts.models import User, UserCompanies
from invoice.export import pick_template
from yaml_manager.models import Yaml


class PickTemplateTests(TestCase):
    """PDF export without a template_id must use the company default, not
    whichever template row the database returns first."""

    def setUp(self):
        self.company = UserCompanies.objects.create(company_name='Acme')
        self.user = User.objects.create_user(username='u', password='pw-12345-x', email='u@x.com',
                                             user_company=self.company)
        self.older = self._template('Older')
        self.default = self._template('Default', is_default=True)
        other_company = UserCompanies.objects.create(company_name='Other')
        other = User.objects.create_user(username='o', password='pw-12345-x', email='o@x.com',
                                         user_company=other_company)
        self.foreign = self._template('Foreign', user=other, company=other_company, is_default=True)

    def _template(self, name, user=None, company=None, is_default=False):
        t = Yaml(user=user or self.user, company=company or self.company,
                 template_name=name, is_default=is_default)
        t.yaml_file.save(f'{name}.yaml', ContentFile(b'Bill: {}'), save=True)
        return t

    def test_no_template_id_uses_company_default(self):
        self.assertEqual(pick_template(self.company), self.default)

    def test_falls_back_to_oldest_when_no_default(self):
        Yaml.objects.filter(company=self.company).update(is_default=False)
        self.assertEqual(pick_template(self.company), self.older)

    def test_explicit_template_id_wins(self):
        self.assertEqual(pick_template(self.company, self.older.id), self.older)

    def test_other_company_template_id_is_rejected(self):
        self.assertIsNone(pick_template(self.company, self.foreign.id))

    def test_company_without_templates(self):
        self.assertIsNone(pick_template(UserCompanies.objects.create(company_name='Empty')))
