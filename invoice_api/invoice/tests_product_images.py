"""
Tests for the line-item image library: upload/list/delete a reusable
`ProductImage`, attach one to a `Product` (line item), and make sure it
stays scoped to the uploader's company.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, User, UserCompanies
from companies.models import CompanySubscription, SubscriptionPlan
from invoice.models import Product, ProductImage

# smallest possible valid PNG (1x1, transparent)
PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


def png_file(name='pic.png'):
    return SimpleUploadedFile(name, PNG_BYTES, content_type='image/png')


class ProductImageTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(
            company_name='Acme', is_varified=True, enable_line_item_images=True)
        self.other_company = UserCompanies.objects.create(
            company_name='Rival', is_varified=True, enable_line_item_images=True)

        # line_item_images is a Pro-plan feature (seeded by migration) that
        # each company must also separately opt into via the toggle above.
        pro_plan = SubscriptionPlan.objects.get(code='pro')
        today = timezone.now().date()
        for company in (self.company, self.other_company):
            CompanySubscription.objects.create(
                company=company, subscription_plan=pro_plan,
                start_date=today, end_date=today + timedelta(days=365),
                status='active')

        self.admin = User.objects.create_user(username='boss', password='x12345678')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        admin_role.users.add(self.admin)

        # a second member of the same company — images should be shared
        self.teammate = User.objects.create_user(username='mate', password='x12345678')
        self.teammate.user_company = self.company
        self.teammate.save()
        admin_role.users.add(self.teammate)

        # a user in a different company — must never see/attach Acme's images
        self.rival = User.objects.create_user(username='rival', password='x12345678')
        self.rival.user_company = self.other_company
        self.rival.save()
        rival_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.other_company)
        rival_role.users.add(self.rival)

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_upload_creates_image_owned_by_company(self):
        client = self.client_as(self.admin)
        res = client.post('/api/product-images/', {'image': png_file()}, format='multipart')
        self.assertEqual(res.status_code, 201, res.data)
        img = ProductImage.objects.get(id=res.data['id'])
        self.assertEqual(img.user, self.admin)
        self.assertEqual(img.company, self.company)
        self.assertEqual(img.original_filename, 'pic.png')
        self.assertTrue(res.data['image'])  # serialized URL present

    def test_teammate_sees_and_reuses_uploaded_image(self):
        uploader = self.client_as(self.admin)
        upload = uploader.post('/api/product-images/', {'image': png_file()}, format='multipart')
        image_id = upload.data['id']

        teammate = self.client_as(self.teammate)
        listing = teammate.get('/api/product-images/')
        self.assertEqual(listing.status_code, 200)
        ids = [row['id'] for row in listing.data['results']]
        self.assertIn(image_id, ids)

    def test_other_company_cannot_see_or_delete_image(self):
        uploader = self.client_as(self.admin)
        upload = uploader.post('/api/product-images/', {'image': png_file()}, format='multipart')
        image_id = upload.data['id']

        rival = self.client_as(self.rival)
        listing = rival.get('/api/product-images/')
        ids = [row['id'] for row in listing.data['results']]
        self.assertNotIn(image_id, ids)

        delete = rival.delete(f'/api/product-images/{image_id}/')
        self.assertEqual(delete.status_code, 404)
        self.assertFalse(ProductImage.objects.get(id=image_id).is_deleted)

    def test_delete_is_soft(self):
        client = self.client_as(self.admin)
        upload = client.post('/api/product-images/', {'image': png_file()}, format='multipart')
        image_id = upload.data['id']

        delete = client.delete(f'/api/product-images/{image_id}/')
        self.assertEqual(delete.status_code, 204)
        img = ProductImage.all_objects.get(id=image_id)
        self.assertTrue(img.is_deleted)
        self.assertFalse(ProductImage.objects.filter(id=image_id).exists())

    def test_attach_image_to_product_line_item(self):
        client = self.client_as(self.admin)
        upload = client.post('/api/product-images/', {'image': png_file()}, format='multipart')
        image_id = upload.data['id']

        create = client.post('/api/product/', {
            'product_properties': '',
            'gst_amount': '0',
            'total_amount': '100',
            'image_id': image_id,
        })
        self.assertEqual(create.status_code, 200, create.data)
        product = Product.objects.get(id=create.data['id'])
        self.assertEqual(product.image_id, image_id)
        self.assertEqual(create.data['image']['id'], image_id)

    def test_cannot_attach_another_companys_image(self):
        uploader = self.client_as(self.admin)
        upload = uploader.post('/api/product-images/', {'image': png_file()}, format='multipart')
        image_id = upload.data['id']

        rival = self.client_as(self.rival)
        create = rival.post('/api/product/', {
            'product_properties': '',
            'gst_amount': '0',
            'total_amount': '100',
            'image_id': image_id,
        })
        self.assertEqual(create.status_code, 400)
        self.assertIn('image_id', create.data)

    def test_image_url_has_no_prefix_by_default(self):
        client = self.client_as(self.admin)
        res = client.post('/api/product-images/', {'image': png_file()}, format='multipart')
        self.assertNotIn('/app/', res.data['image'])
        self.assertIn('/media/', res.data['image'])

    @override_settings(PUBLIC_URL_PREFIX='/app')
    def test_image_url_carries_public_url_prefix_when_set(self):
        client = self.client_as(self.admin)
        res = client.post('/api/product-images/', {'image': png_file()}, format='multipart')
        self.assertIn('/app/media/', res.data['image'])

    def test_product_without_image_still_works(self):
        client = self.client_as(self.admin)
        create = client.post('/api/product/', {
            'product_properties': '',
            'gst_amount': '0',
            'total_amount': '50',
        })
        self.assertEqual(create.status_code, 200, create.data)
        self.assertIsNone(create.data['image'])


class ProductImageFeatureGateTests(APITestCase):
    """The feature needs BOTH a Pro-plan subscription AND the company's own
    opt-in toggle — off by default even on a plan that includes it."""

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.admin = User.objects.create_user(username='boss', password='x12345678')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        admin_role.users.add(self.admin)

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def give_pro_plan(self):
        pro_plan = SubscriptionPlan.objects.get(code='pro')
        today = timezone.now().date()
        CompanySubscription.objects.create(
            company=self.company, subscription_plan=pro_plan,
            start_date=today, end_date=today + timedelta(days=365),
            status='active')
        cache.clear()

    def test_blocked_with_neither_plan_nor_toggle(self):
        client = self.client_as(self.admin)
        res = client.get('/api/product-images/')
        self.assertEqual(res.status_code, 403)

    def test_blocked_with_plan_but_toggle_off(self):
        self.give_pro_plan()
        client = self.client_as(self.admin)
        res = client.get('/api/product-images/')
        self.assertEqual(res.status_code, 403)

    def test_blocked_with_toggle_on_but_no_plan(self):
        self.company.enable_line_item_images = True
        self.company.save(update_fields=['enable_line_item_images'])
        client = self.client_as(self.admin)
        res = client.get('/api/product-images/')
        self.assertEqual(res.status_code, 403)

    def test_allowed_with_both_plan_and_toggle(self):
        self.give_pro_plan()
        self.company.enable_line_item_images = True
        self.company.save(update_fields=['enable_line_item_images'])
        client = self.client_as(self.admin)
        res = client.get('/api/product-images/')
        self.assertEqual(res.status_code, 200)

    def test_image_id_rejected_on_product_when_feature_off(self):
        # Even without ProductImageViewSet access, a crafted image_id must
        # not attach if the company hasn't enabled the feature.
        self.give_pro_plan()
        other = UserCompanies.objects.create(
            company_name='Beta', is_varified=True, enable_line_item_images=True)
        pro_plan = SubscriptionPlan.objects.get(code='pro')
        today = timezone.now().date()
        CompanySubscription.objects.create(
            company=other, subscription_plan=pro_plan,
            start_date=today, end_date=today + timedelta(days=365), status='active')
        other_admin = User.objects.create_user(username='beta_boss', password='x12345678')
        other_admin.user_company = other
        other_admin.is_company_admin = True
        other_admin.save()
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, other)
        role.users.add(other_admin)
        cache.clear()

        image = self.client_as(other_admin).post(
            '/api/product-images/', {'image': png_file()}, format='multipart')
        self.assertEqual(image.status_code, 201, image.data)

        # self.company has the plan but never flipped the toggle on.
        create = self.client_as(self.admin).post('/api/product/', {
            'product_properties': '', 'gst_amount': '0', 'total_amount': '10',
            'image_id': image.data['id'],
        })
        self.assertEqual(create.status_code, 400)
        self.assertIn('image_id', create.data)
