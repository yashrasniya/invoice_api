from rest_framework.test import APITestCase

from accounts.gst_utils import parse_gstin
from accounts.models import User, UserCompanies


class CompanySetupTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', email='o@x.com', password='pw-12345-Xyz!')
        self.client.force_authenticate(self.user)

    def post(self, **extra):
        body = {'company_name': 'Acme', 'company_address': '12 MG Road', 'company_email_id': 'a@acme.com'}
        body.update(extra)
        return self.client.post('/api/user-companies/', body, format='json')

    def test_gstin_derives_state_and_code(self):
        r = self.post(company_gst_number=' 29abcde1234f1z5 ')
        self.assertEqual(r.status_code, 201, r.data)
        c = UserCompanies.objects.get()
        self.assertEqual((c.company_gst_number, c.state_code, c.state), ('29ABCDE1234F1Z5', 29, 'Karnataka'))

    def test_gstin_overrides_a_mismatched_state(self):
        self.post(company_gst_number='29ABCDE1234F1Z5', state='Goa', state_code=30)
        c = UserCompanies.objects.get()
        self.assertEqual((c.state_code, c.state), (29, 'Karnataka'))

    def test_no_gst_is_allowed_when_state_is_chosen(self):
        r = self.post(state='Kerala')
        self.assertEqual(r.status_code, 201, r.data)
        c = UserCompanies.objects.get()
        self.assertIsNone(c.company_gst_number)
        self.assertEqual((c.state_code, c.state), (32, 'Kerala'))

    def test_no_gst_and_no_state_is_rejected(self):
        r = self.post()
        self.assertEqual(r.status_code, 400)
        self.assertIn('state', r.data)

    def test_bad_gstin_is_rejected(self):
        r = self.post(company_gst_number='NOT-A-GSTIN')
        self.assertEqual(r.status_code, 400)
        self.assertIn('company_gst_number', r.data)

    def test_real_world_lengths_are_stored_untruncated(self):
        address = 'Plot 14, Phase 2, Industrial Estate, Peenya, Bengaluru, Karnataka 560058'
        name = 'Sri Venkateswara Traders and Distributors Private Limited'
        r = self.post(state='Karnataka', company_address=address, company_name=name,
                      company_email_id='accounts.department@sri-venkateswara-traders.example.com')
        self.assertEqual(r.status_code, 201, r.data)
        c = UserCompanies.objects.get()
        self.assertEqual((c.company_address, c.company_name), (address, name))

    def test_long_state_name_fits(self):
        self.post(state='Dadra and Nagar Haveli and Daman and Diu')
        self.assertEqual(UserCompanies.objects.get().state_code, 26)

    def test_parse_gstin_rejects_unknown_state_code(self):
        with self.assertRaises(ValueError):
            parse_gstin('99ABCDE1234F1Z5'.replace('99', '25'))
