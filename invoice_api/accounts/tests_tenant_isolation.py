"""Regression tests for BUGS.md C5 (invite takeover), C7 (cross-tenant
customer/vendor edit+delete) and C8 (cross-tenant line items)."""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, User, UserInvite
from rest_framework.test import APITestCase

from accounts.tests_authz import make_company, make_user
from companies.models import (CompanySubscription, Customers, Feature,
                              PlanFeature, Vendor)
from invoice.models import (Invoice, Product, Product_properties,
                            new_product_in_frontend)


def _give_all_permissions(company, user):
    admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, company)
    admin_role.users.add(user)


class TenantTestBase(APITestCase):
    """Two companies, an admin in each, a member and a platform superuser.
    (Not a subclass of AuthzTestCase: that would inherit all of its tests.)"""

    def setUp(self):
        cache.clear()
        self.company_a = make_company('Alpha')
        self.company_b = make_company('Beta')
        self.admin_a = make_user('admin_a', self.company_a, admin=True)
        self.member_a = make_user('member_a', self.company_a)
        self.admin_b = make_user('admin_b', self.company_b, admin=True)
        self.superuser = make_user('root', None, superuser=True)

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class InviteTakeoverTests(TenantTestBase):
    """C5: an invite link must never log in an existing account by itself."""

    def _invite(self, email):
        return UserInvite.objects.create(
            company=self.company_a, email=email, invited_by=self.admin_a,
            expires_at=timezone.now() + timedelta(days=3))

    def test_existing_company_less_account_needs_its_password(self):
        invite = self._invite('root@example.com')
        self.superuser.email = 'root@example.com'
        self.superuser.set_password('right-password-1')
        self.superuser.save()
        pub = APIClient()

        r = pub.post(f'/api/invites/{invite.token}/accept/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertNotIn('access_token', r.cookies)
        r = pub.post(f'/api/invites/{invite.token}/accept/',
                     {'password': 'wrong'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.superuser.refresh_from_db()
        self.assertIsNone(self.superuser.user_company_id)   # untouched
        invite.refresh_from_db()
        self.assertEqual(invite.status, 'pending')           # not consumed

        r = pub.post(f'/api/invites/{invite.token}/accept/',
                     {'password': 'right-password-1'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.superuser.refresh_from_db()
        self.assertEqual(self.superuser.user_company_id, self.company_a.id)

    def test_disabled_account_is_not_reactivated(self):
        invite = self._invite('off@example.com')
        off = make_user('off', None)
        off.email = 'off@example.com'
        off.set_password('right-password-1')
        off.is_active = False
        off.save()
        r = APIClient().post(f'/api/invites/{invite.token}/accept/',
                             {'password': 'right-password-1'}, format='json')
        self.assertEqual(r.status_code, 403)
        off.refresh_from_db()
        self.assertFalse(off.is_active)
        self.assertIsNone(off.user_company_id)


class CustomerVendorIsolationTests(TenantTestBase):
    """C7"""

    def setUp(self):
        super().setUp()
        _give_all_permissions(self.company_a, self.admin_a)
        self.victim_customer = Customers.objects.create(
            name='Victim Ltd', gst_number='29ABCDE1234F1ZW', user=self.admin_b)
        self.victim_vendor = Vendor.objects.create(name='Victim Vendor', user=self.admin_b)
        self.mine = Customers.objects.create(name='Mine', user=self.admin_a)
        self.c = self.client_for(self.admin_a)

    def test_cannot_edit_foreign_customer(self):
        r = self.c.post(f'/api/companies/{self.victim_customer.id}/',
                        {'name': 'Hacked'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.victim_customer.refresh_from_db()
        self.assertEqual(self.victim_customer.name, 'Victim Ltd')
        self.assertEqual(self.victim_customer.user_id, self.admin_b.id)

    def test_cannot_delete_foreign_customer(self):
        r = self.c.delete(f'/api/companies/{self.victim_customer.id}/')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Customers.objects.filter(pk=self.victim_customer.pk).exists())

    def test_cannot_edit_or_delete_foreign_vendor(self):
        r = self.c.post(f'/api/vendors/{self.victim_vendor.id}/',
                        {'name': 'Hacked'}, format='json')
        self.assertEqual(r.status_code, 404)
        r = self.c.delete(f'/api/vendors/{self.victim_vendor.id}/')
        self.assertEqual(r.status_code, 400)
        self.victim_vendor.refresh_from_db()
        self.assertEqual(self.victim_vendor.name, 'Victim Vendor')

    def test_own_customer_edit_and_delete_still_work(self):
        r = self.c.post(f'/api/companies/{self.mine.id}/',
                        {'name': 'Renamed'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.name, 'Renamed')
        self.assertEqual(self.mine.user_id, self.admin_a.id)
        r = self.c.delete(f'/api/companies/{self.mine.id}/')
        self.assertEqual(r.status_code, 204)

    def test_colleague_edit_keeps_original_creator(self):
        _give_all_permissions(self.company_a, self.member_a)
        r = self.client_for(self.member_a).post(
            f'/api/companies/{self.mine.id}/', {'name': 'By colleague'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.user_id, self.admin_a.id)


class LineItemIsolationTests(TenantTestBase):
    """C8"""

    def setUp(self):
        super().setUp()
        self.victim_item = Product.objects.create(
            gst_amount=Decimal('18'), total_amount=Decimal('118'), user=self.admin_b)
        self.victim_invoice = Invoice.objects.create(
            user=self.admin_b, total_final_amount=Decimal('118'))
        self.victim_invoice.products.add(self.victim_item)
        col = new_product_in_frontend.objects.create(user=self.admin_b, size=Decimal('1'))
        self.victim_prop = Product_properties.objects.create(
            new_product_in_frontend=col, value='secret')
        self.victim_item.product_properties.add(self.victim_prop)
        _give_all_permissions(self.company_a, self.admin_a)
        self.c = self.client_for(self.admin_a)
        self.my_invoice = Invoice.objects.create(
            user=self.admin_a, total_final_amount=Decimal('0'))

    def test_cannot_update_foreign_line_item(self):
        r = self.c.post(f'/api/product/{self.victim_item.id}/update/',
                        {'gst_amount': '1', 'total_amount': '1'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.victim_item.refresh_from_db()
        self.assertEqual(self.victim_item.total_amount, Decimal('118'))

    def test_cannot_delete_foreign_line_item(self):
        r = self.c.delete(f'/api/product/{self.victim_item.id}/update/')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Product.objects.filter(pk=self.victim_item.pk).exists())
        self.assertEqual(self.victim_invoice.products.count(), 1)

    def test_cannot_touch_foreign_properties(self):
        r = self.c.post(f'/api/product/properties/{self.victim_prop.id}/update/',
                        {'value': 'changed'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.c.delete(f'/api/product/properties/{self.victim_prop.id}/update/')
        self.assertEqual(r.status_code, 400)
        self.victim_prop.refresh_from_db()
        self.assertEqual(self.victim_prop.value, 'secret')

    def test_cannot_attach_or_detach_foreign_line_item(self):
        r = self.c.post(f'/api/invoice/{self.my_invoice.id}/product/add/',
                        {'product_id': self.victim_item.id}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.my_invoice.products.count(), 0)
        # and cannot detach it from the victim's own invoice either
        r = self.c.post(f'/api/invoice/{self.victim_invoice.id}/product/delete/',
                        {'product_id': self.victim_item.id}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.victim_invoice.products.count(), 1)

    def test_own_line_item_flow_still_works(self):
        r = self.c.post('/api/product/',
                        {'gst_amount': '9', 'total_amount': '59'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        item = Product.objects.get(pk=r.data['id'])
        self.assertEqual(item.user_id, self.admin_a.id)
        r = self.c.post(f'/api/product/{item.id}/update/',
                        {'gst_amount': '10', 'total_amount': '60'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        r = self.c.post(f'/api/invoice/{self.my_invoice.id}/product/add/',
                        {'product_id': item.id}, format='json')
        self.assertEqual(r.status_code, 200)
        r = self.c.delete(f'/api/product/{item.id}/update/')
        self.assertEqual(r.status_code, 204)
