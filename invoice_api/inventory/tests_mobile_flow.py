"""Replays MobileApp/services/inventory.ts calls (JSON, bearer auth)."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from inventory.models import Product
from invoice.tests_numbering import give_plan

User = get_user_model()


class MobileInventoryFlowTest(TestCase):
    def setUp(self):
        cache.clear()   # plan/feature lookups are cached per company id, and ids repeat across tests
        company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.user = User.objects.create_user(username='inv', email='i@e.com', password='pw-123456')
        self.user.user_company = company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(company, ['inventory'])
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, company)
        admin_role.users.add(self.user)
        self.client = APIClient()
        token = self.client.post('/api/login/', {'username': 'inv', 'password': 'pw-123456'},
                                 format='json', HTTP_X_CLIENT='mobile').data['access']
        self.client.cookies.clear()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_CLIENT='mobile')

    def call(self, method, url, body=None, expect=200):
        res = getattr(self.client, method)(url, body, format='json')
        self.assertEqual(res.status_code, expect, res.content)
        return res.data

    def test_product_lifecycle_and_stock(self):
        cat = self.call('post', '/api/inventory/categories/', {'name': 'Tools'}, 201)
        p = self.call('post', '/api/inventory/products/', {
            'sku': 'EAN-1', 'name': 'Hammer', 'description': None, 'category': cat['id'],
            'price': '250.00', 'gst_percentage': '18', 'reorder_level': 5, 'current_stock': 10}, 201)
        self.assertEqual(p['category_name'], 'Tools')

        # unpaginated list + SKU lookup used by the barcode scanner
        hits = self.client.get('/api/inventory/products/', {'search': 'EAN-1'}).data
        self.assertIsInstance(hits, list)
        self.assertEqual(hits[0]['id'], p['id'])

        # edit must not touch stock (the app omits current_stock on update)
        p2 = self.call('patch', f'/api/inventory/products/{p["id"]}/', {
            'sku': 'EAN-1', 'name': 'Hammer 2', 'description': None, 'category': None,
            'price': '260.00', 'gst_percentage': '12', 'reorder_level': 3})
        self.assertEqual(p2['current_stock'], 10)
        self.assertIsNone(p2['category'])

        self.call('post', '/api/inventory/stock-movements/',
                  {'product': p['id'], 'quantity': 4, 'movement_type': 'OUT', 'notes': 'Invoice #9'}, 201)
        self.call('post', '/api/inventory/stock-movements/',
                  {'product': p['id'], 'quantity': 2, 'movement_type': 'IN'}, 201)
        self.assertEqual(Product.objects.get(id=p['id']).current_stock, 8)

        moves = self.client.get('/api/inventory/stock-movements/', {'product': p['id']}).data
        self.assertEqual(len(moves), 2)

        self.call('post', '/api/inventory/stock-movements/',
                  {'product': p['id'], 'quantity': 0, 'movement_type': 'IN'}, 400)

        dup = self.client.post('/api/inventory/products/', {
            'sku': 'EAN-1', 'name': 'Dup', 'price': '1', 'gst_percentage': '0',
            'reorder_level': 0, 'current_stock': 0}, format='json')
        self.assertEqual(dup.status_code, 400)

        self.call('delete', f'/api/inventory/products/{p["id"]}/', None, 204)
        self.call('delete', f'/api/inventory/categories/{cat["id"]}/', None, 204)
