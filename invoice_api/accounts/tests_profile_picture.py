import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from accounts.models import User

MEDIA = tempfile.mkdtemp()


def png(name='me.png'):
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA)
class ProfilePictureTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username='pic', email='pic@x.com', password='pw-12345-Xyz!')
        self.client.force_authenticate(self.user)

    def test_upload_sets_picture_and_replacing_removes_old_file(self):
        r = self.client.post('/api/profile/picture/', {'image': png()}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['profile'])
        first = User.objects.get(pk=self.user.pk).profile.path
        self.client.post('/api/profile/picture/', {'image': png('b.png')}, format='multipart')
        self.assertNotEqual(User.objects.get(pk=self.user.pk).profile.path, first)
        import os
        self.assertFalse(os.path.exists(first))

    def test_rejects_non_image_and_missing_file(self):
        bad = SimpleUploadedFile('x.png', b'not an image', content_type='image/png')
        self.assertEqual(self.client.post('/api/profile/picture/', {'image': bad}, format='multipart').status_code, 400)
        self.assertEqual(self.client.post('/api/profile/picture/', {}, format='multipart').status_code, 400)

    def test_delete_clears_picture(self):
        self.client.post('/api/profile/picture/', {'image': png()}, format='multipart')
        r = self.client.delete('/api/profile/picture/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['profile'])

    def test_requires_login(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.post('/api/profile/picture/', {'image': png()}, format='multipart').status_code, (401, 403))
