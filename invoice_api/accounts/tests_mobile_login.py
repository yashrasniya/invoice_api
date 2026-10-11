"""The mobile app has no cookie jar, so login returns the bearer token in the body
— but only when the client asks for it, so the web response is unchanged."""
from rest_framework.test import APITestCase

from accounts.models import User


class MobileLoginTests(APITestCase):

    def setUp(self):
        User.objects.create_user(username='mob', password='pass-12345', email='m@example.com')

    def login(self, **extra):
        return self.client.post('/api/login/', {'username': 'mob', 'password': 'pass-12345'},
                                format='json', **extra)

    def test_mobile_client_gets_token_in_body(self):
        res = self.login(HTTP_X_CLIENT='mobile')
        self.assertEqual(res.status_code, 200)
        self.assertIn('access', res.data)

    def test_token_authenticates_as_bearer(self):
        token = self.login(HTTP_X_CLIENT='mobile').data['access']
        self.client.cookies.clear()
        res = self.client.get('/api/profile/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['username'], 'mob')

    def test_web_client_body_has_no_token(self):
        res = self.login()
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('access', res.data)
