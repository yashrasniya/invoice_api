from django.test import TestCase

# Create your tests here.
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

    def test_create_user(self):
        print(get_user_model())
        user = get_user_model().objects.create_user(**self.user_data)
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
        self.assertEqual(user.gender, 'Male')
        self.assertEqual(user.dob, '1990-01-01')
        self.assertEqual(user.mobile_number, '1234567890')
        # Add assertions for other fields

    def test_create_superuser(self):
        superuser = get_user_model().objects.create_superuser(**self.user_data)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_staff)
        # Add assertions for other fields

    def test_profile_upload(self):
        profile_file = SimpleUploadedFile("test_profile.txt", b"file_content")
        self.user_data['profile'] = profile_file
        user = get_user_model().objects.create_user(**self.user_data)
        self.assertEqual(user.profile.name, 'accounts/profile/test_profile.txt')

    def test_company_logo_upload(self):
        logo_file = SimpleUploadedFile("test_logo.png", b"image_content", content_type="image/png")
        self.user_data['company_logo'] = logo_file
        user = get_user_model().objects.create_user(**self.user_data)
        self.assertEqual(user.company_logo.name, 'accounts/test_logo.png')

    # Add more test cases for other functionalities and edge cases

