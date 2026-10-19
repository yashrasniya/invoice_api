from datetime import date

from rest_framework.test import APITestCase

from accounts.models import User, UserCompanies
from bill_share.models import BillShare
from companies.models import Customers
from invoice.models import Invoice

URL = '/api/onboarding/'


class OnboardingChecklistTests(APITestCase):
    def setUp(self):
        self.company = UserCompanies.objects.create(company_name='Acme', state='Goa', state_code=30)
        self.admin = self.make_user('admin', is_company_admin=True)
        self.client.force_authenticate(self.admin)

    def make_user(self, name, **fields):
        # the project's create_user() ignores extra fields, so set them afterwards
        user = User.objects.create_user(username=name, email=f'{name}@x.com', password='pw-12345-Xyz!')
        for key, value in {'user_company': self.company, **fields}.items():
            setattr(user, key, value)
        user.save()
        return user

    def steps(self):
        data = self.client.get(URL).data
        return data['visible'], {s['key']: s['done'] for s in data['steps']}

    def test_new_company_has_only_company_step_done(self):
        visible, steps = self.steps()
        self.assertTrue(visible)
        self.assertEqual(steps, {'company': True, 'customer': False, 'invoice': False, 'share': False})

    def test_steps_tick_themselves_from_real_data(self):
        customer = Customers.objects.create(user=self.admin, name='Ravi')
        self.assertTrue(self.steps()[1]['customer'])
        inv = Invoice.objects.create(user=self.admin, receiver=customer, date=date(2026, 8, 1),
                                     total_final_amount=100, gst_final_amount=18, invoice_type='sales')
        self.assertTrue(self.steps()[1]['invoice'])
        BillShare.objects.create(user=self.admin, invoice=inv, to='9999999999')
        visible, steps = self.steps()
        self.assertTrue(all(steps.values()))
        self.assertFalse(visible, 'the checklist hides itself once everything is done')

    def test_purchase_invoice_does_not_count_as_first_invoice(self):
        customer = Customers.objects.create(user=self.admin, name='Ravi')
        Invoice.objects.create(user=self.admin, receiver=customer, date=date(2026, 8, 1),
                               total_final_amount=100, gst_final_amount=18, invoice_type='purchase')
        self.assertFalse(self.steps()[1]['invoice'])

    def test_sharing_a_pdf_is_recorded_by_the_app(self):
        r = self.client.post(URL, {'shared': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.steps()[1]['share'])

    def test_dismiss_hides_the_list_permanently(self):
        self.client.post(URL, {'dismiss': True}, format='json')
        visible, _ = self.steps()
        self.assertFalse(visible)

    def test_teammates_never_see_it(self):
        member = self.make_user('member')
        self.client.force_authenticate(member)
        self.assertEqual(self.client.get(URL).data, {'visible': False, 'steps': []})
        self.assertEqual(self.client.post(URL, {'dismiss': True}, format='json').status_code, 403)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(URL).status_code, (401, 403))
