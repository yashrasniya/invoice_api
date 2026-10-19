from django.conf import settings
from rest_framework.test import APITestCase

from accounts.models import User


class RegisterSignsInTests(APITestCase):
    def test_register_sets_auth_cookie_and_cookie_authenticates(self):
        r = self.client.post('/api/register/', {
            'username': 'newbie', 'email': 'n@x.com', 'first_name': 'N',
            'last_name': 'B', 'mobile_number': '9000000009',
            'password': 'pw-12345-Xyz!'}, format='json')
        self.assertEqual(r.status_code, 201)
        cookie = settings.SIMPLE_JWT['AUTH_COOKIE']
        self.assertIn(cookie, r.cookies)
        self.assertTrue(User.objects.filter(username='newbie').exists())
        # the cookie alone must be enough to reach an authenticated endpoint
        self.assertEqual(self.client.get('/api/profile/').status_code, 200)

    def test_failed_register_sets_no_cookie(self):
        r = self.client.post('/api/register/', {'username': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(settings.SIMPLE_JWT['AUTH_COOKIE'], r.cookies)


class SignupWithoutUsernameTests(APITestCase):
    PAYLOAD = {'email': 'Asha.Rao@x.com', 'first_name': 'Asha', 'mobile_number': '9000000010',
               'password': 'pw-12345-Xyz!'}

    def test_username_and_last_name_are_optional_and_derived_from_email(self):
        r = self.client.post('/api/register/', self.PAYLOAD, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        user = User.objects.get(email='Asha.Rao@x.com')
        self.assertEqual(user.username, 'Asha.Rao')
        self.assertEqual(user.last_name, '')

    def test_derived_username_is_made_unique(self):
        User.objects.create_user(username='asha.rao', email='other@x.com', password='x')
        self.client.post('/api/register/', self.PAYLOAD, format='json')
        self.assertEqual(User.objects.get(email='Asha.Rao@x.com').username, 'Asha.Rao1')

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.client.post('/api/register/', self.PAYLOAD, format='json')
        r = self.client.post('/api/register/', {**self.PAYLOAD, 'email': 'asha.rao@X.com'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('email', r.data)

    def test_can_log_in_with_email(self):
        self.client.post('/api/register/', self.PAYLOAD, format='json')
        self.client.cookies.clear()
        r = self.client.post('/api/login/', {'username': 'asha.rao@x.com', 'password': self.PAYLOAD['password']},
                             format='json')
        self.assertEqual(r.status_code, 200, r.data)
