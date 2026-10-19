import time
from unittest.mock import patch

from django.core import mail
from rest_framework.test import APITestCase

from accounts.mobile import clean_indian_mobile
from accounts.models import SocialAccount, User
from accounts.verification import make_token

PAYLOAD = {'email': 'asha@x.com', 'first_name': 'Asha', 'last_name': 'Rao', 'mobile_number': '98765 43210',
           'password': 'pw-12345-Xyz!'}
GOOGLE = 'accounts.api.views.google_id_token.verify_oauth2_token'
PHONE = 'accounts.phone_verify.google_id_token.verify_firebase_token'


class MobileNumberTests(APITestCase):
    def test_clean_indian_mobile(self):
        for raw in ('+91 98765 43210', '098765-43210', '9876543210', '91 9876543210'):
            self.assertEqual(clean_indian_mobile(raw), '9876543210', raw)
        for raw in ('12345', '5876543210', '', None, '+1 415 555 0100'):
            self.assertIsNone(clean_indian_mobile(raw), raw)

    def test_formatted_number_is_accepted_and_stored_normalised(self):
        r = self.client.post('/api/register/', {**PAYLOAD, 'mobile_number': '+91 98765 43210'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(User.objects.get().mobile_number, '9876543210')

    def test_invalid_number_is_a_field_error(self):
        r = self.client.post('/api/register/', {**PAYLOAD, 'mobile_number': '12345'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('mobile_number', r.data)


class SingleRequestSignupTests(APITestCase):
    def test_mobile_client_gets_a_session_from_register_itself(self):
        r = self.client.post('/api/register/', PAYLOAD, format='json', HTTP_X_CLIENT='mobile')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['access'])
        self.assertEqual(r.data['email'], 'asha@x.com')
        self.assertFalse(r.data['email_verified'])
        # the token alone is enough to call an authenticated endpoint
        self.client.cookies.clear()
        auth = self.client.get('/api/profile/', HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(auth.status_code, 200)

    def test_web_client_gets_no_token_in_the_body(self):
        r = self.client.post('/api/register/', PAYLOAD, format='json')
        self.assertNotIn('access', r.data)

    def test_duplicate_email_has_a_code_the_app_can_act_on(self):
        self.client.post('/api/register/', PAYLOAD, format='json')
        r = self.client.post('/api/register/', {**PAYLOAD, 'email': 'ASHA@x.com'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'email_exists')
        self.assertIn('email', r.data)


class PhoneProofAtSignupTests(APITestCase):
    def claims(self, phone='+919876543210'):
        return {'iss': 'https://securetoken.google.com/proj', 'sub': 'fb1', 'user_id': 'fb1', 'phone_number': phone,
                'firebase': {'sign_in_provider': 'phone'}}

    def register(self, **extra):
        return self.client.post('/api/register/', {**PAYLOAD, 'phone_id_token': 'tok', **extra}, format='json')

    @patch(PHONE)
    def test_matching_proof_makes_the_number_verified_and_links_phone_login(self, verify):
        verify.return_value = self.claims()
        with self.settings(FIREBASE_PROJECT_ID='proj'):
            r = self.register()
        self.assertEqual(r.status_code, 201, r.data)
        user = User.objects.get()
        self.assertTrue(user.mobile_verified)
        self.assertTrue(SocialAccount.objects.filter(user=user, provider='phone', provider_uid='fb1').exists())

    @patch(PHONE)
    def test_proof_for_a_different_number_is_rejected(self, verify):
        verify.return_value = self.claims(phone='+919000000000')
        with self.settings(FIREBASE_PROJECT_ID='proj'):
            r = self.register()
        self.assertEqual(r.status_code, 400)
        self.assertIn('phone_id_token', r.data)
        self.assertFalse(User.objects.exists())

    @patch(PHONE)
    def test_bad_token_is_rejected(self, verify):
        verify.side_effect = ValueError('bad')
        with self.settings(FIREBASE_PROJECT_ID='proj'):
            self.assertEqual(self.register().status_code, 400)

    def test_no_proof_leaves_the_number_unverified(self):
        self.client.post('/api/register/', PAYLOAD, format='json')
        self.assertFalse(User.objects.get().mobile_verified)


class GooglePreRegistrationTests(APITestCase):
    @patch(GOOGLE)
    def test_unverified_email_account_is_taken_back(self, verify):
        self.client.post('/api/register/', {**PAYLOAD, 'email': 'victim@x.com'}, format='json', HTTP_X_CLIENT='mobile')
        squatter = User.objects.get(email='victim@x.com')
        old_token = self.client.post('/api/login/', {'username': 'victim@x.com', 'password': PAYLOAD['password']},
                                     format='json', HTTP_X_CLIENT='mobile').data['access']
        time.sleep(1.1)   # JWT 'iat' has one-second resolution
        verify.return_value = {'sub': 'g1', 'email': 'victim@x.com', 'email_verified': True, 'given_name': 'V'}
        r = self.client.post('/api/google-login/', {'credential': 'x'}, format='json', HTTP_X_CLIENT='mobile')
        self.assertEqual(r.status_code, 200, r.data)
        squatter.refresh_from_db()
        self.assertTrue(squatter.email_verified)
        self.assertFalse(squatter.has_usable_password(), "the squatter's password must stop working")
        self.client.cookies.clear()
        stale = self.client.get('/api/profile/', HTTP_AUTHORIZATION=f'Bearer {old_token}')
        self.assertEqual(stale.status_code, 401, "the squatter's existing session must die")
        fresh = self.client.get('/api/profile/', HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(fresh.status_code, 200, 'the real owner is signed in')

    @patch(GOOGLE)
    def test_verified_email_account_keeps_its_password(self, verify):
        user = User.objects.create_user(username='kept', email='kept@x.com', password='pw-12345-Xyz!')
        user.email_verified = True
        user.save()
        verify.return_value = {'sub': 'g2', 'email': 'kept@x.com', 'email_verified': True}
        self.client.post('/api/google-login/', {'credential': 'x'}, format='json')
        user.refresh_from_db()
        self.assertTrue(user.has_usable_password())


class EmailVerificationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', email='u@x.com', password='pw-12345-Xyz!',
                                             first_name='U')
        self.client.force_authenticate(self.user)

    def test_link_verifies_the_address(self):
        r = self.client.get(f'/api/verify-email/{make_token(self.user)}/')
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_tampered_or_stale_links_are_refused(self):
        self.assertEqual(self.client.get('/api/verify-email/garbage/').status_code, 400)
        token = make_token(self.user)
        self.user.email = 'changed@x.com'
        self.user.save()
        self.assertEqual(self.client.get(f'/api/verify-email/{token}/').status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_resend_sends_one_mail_then_rate_limits(self):
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'), \
                patch('accounts.verification.threading.Thread') as thread:
            thread.side_effect = lambda target, args, daemon: type('T', (), {'start': lambda s: target(*args)})()
            first = self.client.post('/api/resend-verification/')
            second = self.client.post('/api/resend-verification/')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/api/verify-email/', mail.outbox[0].body)
        self.assertEqual(second.status_code, 429)

    def test_users_cannot_verify_themselves_through_the_profile_endpoint(self):
        self.client.post('/api/profile/', {'email_verified': True, 'mobile_verified': True}, format='json')
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified or self.user.mobile_verified)
