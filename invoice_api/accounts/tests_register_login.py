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
