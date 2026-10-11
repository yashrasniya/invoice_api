"""Device registration + best-effort push delivery (Expo's service is mocked)."""
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import DeviceToken, UserCompanies
from accounts.push import is_expo_token, send_push
from invoice.models import InvoiceExtractionLog
from invoice.tests_numbering import give_plan

User = get_user_model()
TOKEN = 'ExponentPushToken[abc123]'


class DeviceRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a = User.objects.create_user(username='a', email='a@e.com', password='x')
        self.b = User.objects.create_user(username='b', email='b@e.com', password='x')
        self.ca = APIClient(); self.ca.force_authenticate(user=self.a)
        self.cb = APIClient(); self.cb.force_authenticate(user=self.b)

    def test_token_validation(self):
        self.assertTrue(is_expo_token(TOKEN))
        for bad in ('', 'abc', 'ExponentPushToken[', None, 123):
            self.assertFalse(is_expo_token(bad))
        res = self.ca.post('/api/devices/', {'token': 'not-a-token'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_register_is_idempotent_and_requires_auth(self):
        self.assertEqual(APIClient().post('/api/devices/', {'token': TOKEN}, format='json').status_code, 401)
        for _ in range(2):
            self.assertEqual(self.ca.post('/api/devices/', {'token': TOKEN, 'platform': 'ios'}, format='json').status_code, 201)
        self.assertEqual(DeviceToken.objects.count(), 1)

    def test_phone_moves_to_whoever_signed_in_last(self):
        self.ca.post('/api/devices/', {'token': TOKEN}, format='json')
        self.cb.post('/api/devices/', {'token': TOKEN}, format='json')
        self.assertEqual(DeviceToken.objects.get(token=TOKEN).user, self.b)

    def test_unregister_only_own_device(self):
        self.ca.post('/api/devices/', {'token': TOKEN}, format='json')
        self.cb.delete('/api/devices/', {'token': TOKEN}, format='json')   # someone else: no effect
        self.assertEqual(DeviceToken.objects.count(), 1)
        self.assertEqual(self.ca.delete('/api/devices/', {'token': TOKEN}, format='json').status_code, 204)
        self.assertEqual(DeviceToken.objects.count(), 0)


class SendPushTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username='p', email='p@e.com', password='x')

    def test_no_devices_means_no_request(self):
        with mock.patch('accounts.push.requests.post') as post:
            self.assertEqual(send_push(self.u, 't', 'b'), 0)
            post.assert_not_called()

    @mock.patch('accounts.push.requests.post')
    def test_sends_and_prunes_dead_tokens(self, post):
        DeviceToken.objects.create(user=self.u, token='ExponentPushToken[ok]')
        DeviceToken.objects.create(user=self.u, token='ExponentPushToken[dead]')
        post.return_value = mock.Mock(json=lambda: {'data': [
            {'status': 'ok'},
            {'status': 'error', 'details': {'error': 'DeviceNotRegistered'}},
        ]})
        # order of the .values_list() is by id, matching creation order
        self.assertEqual(send_push(self.u, 'Hi', 'There', {'k': 1}), 1)
        sent = post.call_args.kwargs['json']
        self.assertEqual({m['to'] for m in sent}, {'ExponentPushToken[ok]', 'ExponentPushToken[dead]'})
        self.assertEqual(sent[0]['title'], 'Hi')
        self.assertEqual(list(DeviceToken.objects.values_list('token', flat=True)), ['ExponentPushToken[ok]'])

    @mock.patch('accounts.push.requests.post', side_effect=RuntimeError('network down'))
    def test_failure_is_swallowed(self, _):
        DeviceToken.objects.create(user=self.u, token=TOKEN)
        self.assertEqual(send_push(self.u, 't', 'b'), 0)    # must not raise


class OcrCallbackPushTests(TestCase):
    def setUp(self):
        cache.clear()
        company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.u = User.objects.create_user(username='o', email='o@e.com', password='x')
        self.u.user_company = company
        self.u.save()
        give_plan(company, ['invoicing', 'purchases_invoice'])
        DeviceToken.objects.create(user=self.u, token=TOKEN)
        self.job = uuid.uuid4()
        InvoiceExtractionLog.objects.create(user=self.u, file='invoices/x.jpg', job_id=self.job, status='queued')
        self.c = APIClient(); self.c.force_authenticate(user=self.u)

    @mock.patch('accounts.push.requests.post')
    def test_completion_sends_push(self, post):
        post.return_value = mock.Mock(json=lambda: {'data': [{'status': 'ok'}]})
        res = self.c.post(f'/api/purchase/callback/{self.job}/', {'status': 'done', 'invoice_type': 'purchase'}, format='json')
        self.assertEqual(res.status_code, 200)
        msg = post.call_args.kwargs['json'][0]
        self.assertEqual(msg['title'], 'Bill scanned')
        self.assertEqual(msg['data']['type'], 'ocr')

    @mock.patch('accounts.push.requests.post')
    def test_in_progress_status_stays_silent(self, post):
        self.c.post(f'/api/purchase/callback/{self.job}/', {'status': 'Extraction Started'}, format='json')
        post.assert_not_called()

    @mock.patch('accounts.push.requests.post')
    def test_failure_sends_failure_push(self, post):
        post.return_value = mock.Mock(json=lambda: {'data': [{'status': 'ok'}]})
        self.c.post(f'/api/purchase/callback/{self.job}/', {'status': 'failed'}, format='json')
        self.assertEqual(post.call_args.kwargs['json'][0]['title'], 'Bill scan failed')
