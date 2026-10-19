"""Asking to delete an account locks it at once and emails the admin; the data goes when an admin runs the
admin action, or `purge_deleted_accounts` after 40 days."""
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts import deletion
from accounts.models import DeviceToken, User, UserCompanies
from companies.models import Customers
from invoice.models import Invoice

URL = '/api/account/delete/'


@override_settings(ACCOUNT_DELETION_NOTIFY_EMAILS=['admin@example.com'],
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AccountDeletionTests(APITestCase):

    def setUp(self):
        self.company = UserCompanies.objects.create(company_name='Acme')
        self.user = User.objects.create_user(username='owner', password='pass-12345', email='o@example.com')
        User.objects.filter(pk=self.user.pk).update(user_company=self.company, is_company_admin=True)
        self.user.refresh_from_db()
        self.client.force_authenticate(self.user)

    def request_deletion(self, **body):
        return self.client.post(URL, {'confirm': 'DELETE', 'password': 'pass-12345', **body}, format='json')

    def test_requires_confirm_and_password(self):
        self.assertEqual(self.client.post(URL, {'password': 'pass-12345'}, format='json').status_code, 400)
        self.assertEqual(self.request_deletion(password='nope').status_code, 400)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deletion_requested_at)

    def test_locks_account_and_emails_admin(self):
        DeviceToken.objects.create(user=self.user, token='ExponentPushToken[x]', platform='android')
        res = self.request_deletion()
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.deletion_requested_at)
        self.assertEqual(self.user.device_tokens.count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['admin@example.com'])
        self.assertIn('owner', mail.outbox[0].body)

    def test_google_only_account_needs_no_password(self):
        self.user.set_unusable_password()
        self.user.save()
        self.assertEqual(self.client.post(URL, {'confirm': 'DELETE'}, format='json').status_code, 200)

    def test_superuser_cannot_delete(self):
        boss = User.objects.create_superuser(username='boss', password='pass-12345', email='b@example.com')
        self.client.force_authenticate(boss)
        self.assertEqual(self.request_deletion().status_code, 403)

    def test_deleted_account_sees_deleted_message_on_login(self):
        self.request_deletion()
        self.client.force_authenticate(None)
        res = self.client.post('/api/login/', {'username': 'owner', 'password': 'pass-12345'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data['error'], 'This account has been deleted.')
        # a wrong password learns nothing about the account
        res = self.client.post('/api/login/', {'username': 'owner', 'password': 'wrong'}, format='json')
        self.assertEqual(res.data['error'], 'password is wrong!')

    def test_purge_removes_user_their_data_and_empty_company(self):
        customer = Customers.objects.create(name='C', user=self.user)
        Invoice.objects.create(user=self.user, receiver=customer)
        self.request_deletion()
        self.user.refresh_from_db()
        deletion.purge_user(self.user)
        self.assertFalse(User.objects.filter(username='owner').exists())
        self.assertFalse(Invoice.all_objects.filter(user_id=self.user.id).exists())
        self.assertFalse(UserCompanies.objects.filter(pk=self.company.pk).exists())

    def test_purge_keeps_company_that_still_has_members(self):
        member = User.objects.create_user(username='member', password='x-12345678')
        User.objects.filter(pk=member.pk).update(user_company=self.company)
        self.request_deletion()
        self.user.refresh_from_db()
        deletion.purge_user(self.user)
        self.assertTrue(UserCompanies.objects.filter(pk=self.company.pk).exists())

    def test_purge_refuses_someone_who_did_not_ask(self):
        with self.assertRaises(ValueError):
            deletion.purge_user(self.user)

    def test_command_deletes_only_after_40_days(self):
        self.request_deletion()
        call_command('purge_deleted_accounts', stdout=StringIO())
        self.assertTrue(User.objects.filter(username='owner').exists())
        User.objects.filter(pk=self.user.pk).update(deletion_requested_at=timezone.now() - timedelta(days=41))
        call_command('purge_deleted_accounts', stdout=StringIO())
        self.assertFalse(User.objects.filter(username='owner').exists())
