"""Deleting a company from the Django admin (row delete and bulk "delete selected").

The cascade removes the company's roles, groups, permissions and subscriptions, whose post_delete signals write
AuditLog rows. Those rows used to point at the company being deleted, so SQLite's deferred FK check failed at commit
(IntegrityError: FOREIGN KEY constraint failed). TestCase never commits, so each test runs the FK check itself."""
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from accounts.models import (AuditLog, CompanyPermission, CompanyRole, User, UserCompanies,
                             UserDirectPermission)


class CompanyAdminDeleteTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(username='boss', password='pass-12345', email='b@example.com')
        self.client.force_login(self.admin)
        self.a = self.make_company('Acme')
        self.b = self.make_company('Beta')
        AuditLog.objects.all().delete()  # bulk queryset delete bypasses the append-only model guard

    def make_company(self, name):
        # runs the on_commit bootstrap: system roles + trial/free subscription
        with self.captureOnCommitCallbacks(execute=True):
            company = UserCompanies.objects.create(company_name=name)
        member = User.objects.create_user(username=f'{name.lower()}-owner', password='pass-12345')
        User.objects.filter(pk=member.pk).update(user_company=company)
        UserDirectPermission.objects.create(
            user=member, company=company, permission=CompanyPermission.objects.first(), is_granted=True)
        self.assertTrue(CompanyRole.objects.filter(company=company).exists())
        return company

    def assert_no_dangling_fks(self):
        connection.check_constraints()  # PRAGMA foreign_key_check: raises IntegrityError on a dangling row

    def test_bulk_delete_selected(self):
        url = reverse('admin:accounts_usercompanies_changelist')
        res = self.client.post(url, {'action': 'delete_selected', '_selected_action': [self.a.pk, self.b.pk],
                                     'post': 'yes'})
        self.assertEqual(res.status_code, 302)
        self.assert_no_dangling_fks()
        self.assertFalse(UserCompanies.objects.filter(pk__in=[self.a.pk, self.b.pk]).exists())
        self.assertFalse(AuditLog.objects.filter(company_id__in=[self.a.pk, self.b.pk]).exists())
        self.assertFalse(User.objects.filter(username__in=['acme-owner', 'beta-owner']).exists())

    def test_single_row_delete(self):
        url = reverse('admin:accounts_usercompanies_delete', args=[self.a.pk])
        res = self.client.post(url, {'post': 'yes'})
        self.assertEqual(res.status_code, 302)
        self.assert_no_dangling_fks()
        self.assertFalse(UserCompanies.objects.filter(pk=self.a.pk).exists())
        self.assertTrue(UserCompanies.objects.filter(pk=self.b.pk).exists())

    def test_orm_delete_outside_admin(self):
        UserCompanies.objects.filter(pk=self.a.pk).delete()
        self.assert_no_dangling_fks()

    def test_normal_deletes_are_still_audited(self):
        # only deletes started on a company skip the audit row
        UserDirectPermission.objects.filter(company=self.b).first().delete()
        self.assertTrue(AuditLog.objects.filter(company=self.b, action='REVOKE').exists())

    def test_company_with_superuser_is_protected(self):
        User.objects.filter(pk=self.admin.pk).update(user_company=self.a)
        url = reverse('admin:accounts_usercompanies_changelist')
        res = self.client.post(url, {'action': 'delete_selected', '_selected_action': [self.a.pk], 'post': 'yes'})
        self.assertEqual(res.status_code, 200)  # "Cannot delete" page, nothing removed
        self.assertContains(res, "Superuser &#x27;boss&#x27;")
        self.assertTrue(UserCompanies.objects.filter(pk=self.a.pk).exists())
        res = self.client.post(reverse('admin:accounts_usercompanies_delete', args=[self.a.pk]), {'post': 'yes'})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(UserCompanies.objects.filter(pk=self.a.pk).exists())
