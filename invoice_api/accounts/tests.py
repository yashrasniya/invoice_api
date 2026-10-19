import datetime

from django.test import TestCase
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

class UserModelTestCase(TestCase):
    def setUp(self):
        self.user_data = {
            'username': 'testuser',
            'password': 'testpassword',
            'first_name': 'John',
            'last_name': 'Doe',
            'gender': 'Male',
            'dob': '1990-01-01',
            'mobile_number': '1234567890',
            # Add other necessary fields for your specific case
        }

    def _create_user(self):
        # User_manager.create_user only takes username/email/password, so the profile fields are set afterwards.
        data = dict(self.user_data)
        profile_fields = {k: data.pop(k) for k in ('first_name', 'last_name', 'gender', 'dob', 'mobile_number', 'profile')
                          if k in data}
        user = get_user_model().objects.create_user(**data)
        for key, value in profile_fields.items():
            setattr(user, key, value)
        user.save()
        user.refresh_from_db()
        return user

    def test_create_user(self):
        user = self._create_user()
        self.assertEqual(user.username, 'testuser')
        self.assertTrue(user.check_password('testpassword'))
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
        self.assertEqual(user.gender, 'Male')
        self.assertEqual(user.dob, datetime.date(1990, 1, 1))
        self.assertEqual(user.mobile_number, '1234567890')

    def test_create_superuser(self):
        superuser = get_user_model().objects.create_superuser(**self.user_data)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_staff)
        # Add assertions for other fields

    def test_profile_upload(self):
        self.user_data['profile'] = SimpleUploadedFile("test_profile.txt", b"file_content")
        user = self._create_user()
        self.assertTrue(user.profile.name.startswith('accounts/profile/test_profile'))
        user.profile.delete(save=False)  # don't leave the upload in MEDIA_ROOT

    def test_company_logo_upload(self):
        # The logo belongs to the company (UserCompanies), not the user.
        logo = SimpleUploadedFile("test_logo.png", b"image_content", content_type="image/png")
        company = UserCompanies(company_name='Acme', company_logo=logo)
        company.company_logo.save('test_logo.png', logo, save=False)
        self.assertTrue(company.company_logo.name.startswith('accounts/test_logo'))
        company.company_logo.delete(save=False)

    # Add more test cases for other functionalities and edge cases


from unittest.mock import patch
from django.urls import reverse
from django.test import override_settings
from accounts.models import SocialAccount, UserCompanies
from invoice.models import new_product_in_frontend
from yaml_manager.models import Yaml

@override_settings(REST_FRAMEWORK={
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'accounts.authenticate.CustomAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {}
})
class GoogleLoginTestCase(TestCase):

    def setUp(self):
        self.url = '/api/google-login/'
        self.login_url = '/api/login/'
        self.client_id = 'dummy-client-id.apps.googleusercontent.com'
        # Set settings value for testing in case it's not set
        from django.conf import settings
        settings.GOOGLE_OAUTH_CLIENT_ID = self.client_id

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_google_login_new_user_success(self, mock_verify):
        # Claim mock
        mock_verify.return_value = {
            'sub': '1234567890',
            'email': 'newuser@example.com',
            'email_verified': True,
            'given_name': 'Google',
            'family_name': 'User',
            'picture': 'http://example.com/pic.jpg'
        }

        response = self.client.post(self.url, {'credential': 'valid-credential-string'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        # Verify user creation
        User = get_user_model()
        user = User.objects.filter(email='newuser@example.com').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.first_name, 'Google')
        self.assertEqual(user.last_name, 'User')
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.is_company_admin)
        
        # Verify SocialAccount creation
        social = SocialAccount.objects.filter(user=user, provider='google', provider_uid='1234567890').first()
        self.assertIsNotNone(social)
        self.assertEqual(social.picture_url, 'http://example.com/pic.jpg')
        
        # Verify default templates/properties setup
        self.assertTrue(new_product_in_frontend.objects.filter(user=user, input_title='Description').exists())
        self.assertTrue(new_product_in_frontend.objects.filter(user=user, input_title='Quantity').exists())
        self.assertTrue(new_product_in_frontend.objects.filter(user=user, input_title='Rate').exists())
        self.assertTrue(new_product_in_frontend.objects.filter(user=user, input_title='GST').exists())
        
        # Verify cookie setting
        self.assertIn('access_token', response.cookies)
        self.assertEqual(response.data['username'], user.username)
        self.assertTrue(response.data['created'])

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_google_login_existing_user_link(self, mock_verify):
        # Create user via password login registration
        User = get_user_model()
        user = User.objects.create_user(username='existinguser', email='existing@example.com', password='password')
        user.email_verified = True      # a proven address: linking keeps the password working
        user.save()
        self.assertTrue(user.has_usable_password())

        mock_verify.return_value = {
            'sub': '987654321',
            'email': 'existing@example.com',
            'email_verified': True,
            'given_name': 'Google',
            'family_name': 'Link',
            'picture': 'http://example.com/link.jpg'
        }

        response = self.client.post(self.url, {'credential': 'valid-credential-string'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # User is linked and remains password active
        user.refresh_from_db()
        self.assertTrue(user.has_usable_password())
        social = SocialAccount.objects.filter(user=user, provider='google', provider_uid='987654321').first()
        self.assertIsNotNone(social)
        self.assertFalse(response.data['created'])

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_google_login_existing_linked_user(self, mock_verify):
        User = get_user_model()
        user = User.objects.create_user(username='linkeduser', email='linked@example.com', password='password')
        social = SocialAccount.objects.create(user=user, provider='google', provider_uid='111222333', email='linked@example.com')
        
        mock_verify.return_value = {
            'sub': '111222333',
            'email': 'linked@example.com',
            'email_verified': True,
            'given_name': 'Google',
            'family_name': 'Linked',
            'picture': 'http://example.com/linked.jpg'
        }

        response = self.client.post(self.url, {'credential': 'valid-credential-string'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['created'])
        social.refresh_from_db()
        self.assertIsNotNone(social.last_login_at)

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_google_login_inactive_user(self, mock_verify):
        User = get_user_model()
        user = User.objects.create_user(username='inactiveuser', email='inactive@example.com', password='password')
        user.is_active = False
        user.save()
        SocialAccount.objects.create(user=user, provider='google', provider_uid='inactive_sub', email='inactive@example.com')

        mock_verify.return_value = {
            'sub': 'inactive_sub',
            'email': 'inactive@example.com',
            'email_verified': True
        }

        response = self.client.post(self.url, {'credential': 'valid-credential'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_google_login_unverified_email(self, mock_verify):
        mock_verify.return_value = {
            'sub': 'unverified_sub',
            'email': 'unverified@example.com',
            'email_verified': False
        }

        response = self.client.post(self.url, {'credential': 'valid-credential'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertIn('not verified', response.data['error'])

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_google_login_invalid_token(self, mock_verify):
        mock_verify.side_effect = ValueError("Invalid signature")

        response = self.client.post(self.url, {'credential': 'bad-token'}, content_type='application/json')
        self.assertEqual(response.status_code, 401)
        self.assertIn('Invalid or expired', response.data['error'])

    def test_google_login_missing_credential(self):
        response = self.client.post(self.url, {}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Missing Google credential', response.data['error'])

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_google_login_username_collision(self, mock_verify):
        User = get_user_model()
        # Create a user with username 'colliding'
        User.objects.create_user(username='colliding', email='other@example.com', password='password')

        mock_verify.return_value = {
            'sub': 'collision_sub',
            'email': 'colliding@example.com',
            'email_verified': True,
            'given_name': 'Col',
            'family_name': 'Lide'
        }

        response = self.client.post(self.url, {'credential': 'valid-credential'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'colliding1')

    @patch('accounts.api.views.google_id_token.verify_oauth2_token')
    def test_traditional_login_hint_for_google_user(self, mock_verify):
        # Create Google login user
        mock_verify.return_value = {
            'sub': 'google_only_sub',
            'email': 'googleonly@example.com',
            'email_verified': True,
            'given_name': 'GoogleOnly',
            'family_name': 'User'
        }
        self.client.post(self.url, {'credential': 'valid'}, content_type='application/json')

        # Now try to log in via password using username or email
        response = self.client.post(self.login_url, {'username': 'googleonly', 'password': 'some-password'}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('uses Google Sign-In', response.data['error'])


