from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import SocialAccount, User

PROJECT = 'demo-project'
URL = '/api/phone-login/'
VERIFY = 'accounts.phone_verify.google_id_token.verify_firebase_token'


def claims(phone='+919876543210', uid='fb-uid-1', provider='phone', iss=f'https://securetoken.google.com/{PROJECT}'):
    return {'iss': iss, 'sub': uid, 'user_id': uid, 'phone_number': phone, 'firebase': {'sign_in_provider': provider}}


@override_settings(FIREBASE_PROJECT_ID=PROJECT)
class PhoneLoginTests(APITestCase):
    def login(self, **kw):
        return self.client.post(URL, {'id_token': 'tok'}, format='json', HTTP_X_CLIENT='mobile', **kw)

    @patch(VERIFY)
    def test_new_number_creates_account_and_returns_token(self, verify):
        verify.return_value = claims()
        r = self.login()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['created'])
        self.assertTrue(r.data['access'])
        user = User.objects.get(mobile_number='9876543210')
        self.assertFalse(user.has_usable_password())
        self.assertTrue(SocialAccount.objects.filter(user=user, provider='phone', provider_uid='fb-uid-1').exists())

    @patch(VERIFY)
    def test_existing_account_with_same_number_is_linked(self, verify):
        existing = User.objects.create_user(username='ravi', email='r@x.com', password='pw-12345-Xyz!')
        existing.mobile_number = '98765 43210'      # stored loosely formatted
        existing.mobile_verified = True             # proven earlier, so signing in by SMS reaches this account
        existing.save()
        verify.return_value = claims()
        r = self.login()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data['created'])
        self.assertEqual(r.data['username'], 'ravi')
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(SocialAccount.objects.filter(user=existing, provider='phone').exists())

    @patch(VERIFY)
    def test_second_login_uses_the_link_even_if_number_changed(self, verify):
        verify.return_value = claims()
        self.login()
        user = User.objects.get(mobile_number='9876543210')
        user.mobile_number = '9000000000'
        user.save()
        r = self.login()
        self.assertFalse(r.data['created'])
        self.assertEqual(User.objects.count(), 1)

    @patch(VERIFY)
    def test_inactive_account_is_refused(self, verify):
        User.objects.create_user(username='gone', password='x', ).__class__.objects.filter(username='gone').update(
            mobile_number='9876543210', mobile_verified=True, is_active=False)
        verify.return_value = claims()
        self.assertEqual(self.login().status_code, 403)
        self.assertEqual(User.objects.count(), 1)

    @patch(VERIFY)
    def test_invalid_token_is_rejected(self, verify):
        verify.side_effect = ValueError('bad')
        self.assertEqual(self.login().status_code, 401)

    @patch(VERIFY)
    def test_non_phone_firebase_token_is_rejected(self, verify):
        verify.return_value = claims(provider='google.com')
        self.assertEqual(self.login().status_code, 401)

    @patch(VERIFY)
    def test_wrong_issuer_is_rejected(self, verify):
        verify.return_value = claims(iss='https://securetoken.google.com/other')
        self.assertEqual(self.login().status_code, 401)

    def test_missing_token(self):
        self.assertEqual(self.client.post(URL, {}, format='json').status_code, 400)

    @override_settings(FIREBASE_PROJECT_ID='')
    def test_unconfigured_returns_503(self):
        self.assertEqual(self.login().status_code, 503)


@override_settings(FIREBASE_PROJECT_ID=PROJECT)
class PreRegistrationTests(APITestCase):
    """A number typed into signup proves nothing; only the SMS check does."""

    @patch(VERIFY)
    def test_unverified_claim_is_withdrawn_not_inherited(self, verify):
        squatter = User.objects.create_user(username='squatter', email='s@x.com', password='pw-12345-Xyz!')
        squatter.mobile_number = '9876543210'
        squatter.save()
        verify.return_value = claims()
        r = self.client.post(URL, {'id_token': 'tok'}, format='json', HTTP_X_CLIENT='mobile')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['created'], 'the real owner gets their own account')
        self.assertNotEqual(r.data['username'], 'squatter')
        squatter.refresh_from_db()
        self.assertEqual(squatter.mobile_number, '')
        self.assertFalse(squatter.mobile_verified)

    @patch(VERIFY)
    def test_successful_phone_login_marks_the_number_verified(self, verify):
        verify.return_value = claims()
        self.client.post(URL, {'id_token': 'tok'}, format='json', HTTP_X_CLIENT='mobile')
        self.assertTrue(User.objects.get(mobile_number='9876543210').mobile_verified)
