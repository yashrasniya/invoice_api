from datetime import datetime, timedelta, time as dt_time, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import (CompanySubscription, Feature, PlanFeature,
                              SubscriptionPlan)
from invoice.models import InvoiceExtractionLog
from invoice.api.pipline import extraction_state, extracted_summary

User = get_user_model()


def give_plan(company, feature_codes, limits=None):
    plan = SubscriptionPlan.objects.create(
        name=f'Plan {company.id}', code=f'plan_{company.id}',
        monthly_price=1, yearly_price=10)
    for code in feature_codes:
        feat, _ = Feature.objects.get_or_create(code=code, defaults={'name': code})
        PlanFeature.objects.create(subscription_plan=plan, feature=feat,
                                   limits=(limits or {}).get(code, {}))
    today = timezone.now().date()
    CompanySubscription.objects.create(
        company=company, subscription_plan=plan, start_date=today,
        end_date=today + timedelta(days=30), status='active')
    return plan


class ExtractionHelpersTest(TestCase):
    def test_state_mapping(self):
        self.assertEqual(extraction_state('done'), 'completed')
        self.assertEqual(extraction_state('success'), 'completed')
        self.assertEqual(extraction_state('SUCCESS'), 'completed')
        self.assertEqual(extraction_state('error'), 'failed')
        self.assertEqual(extraction_state('Extraction Started'), 'processing')
        self.assertEqual(extraction_state(None), 'processing')

    def test_summary_prefers_meta_data(self):
        log = InvoiceExtractionLog(
            meta_data={'invoice_number': 'INV-9', 'total_final_amount': 500},
            response_data={'invoice_number': 'OLD-1', 'gst_final_amount': 90},
        )
        out = extracted_summary(log)
        self.assertEqual(out['invoice_number'], 'INV-9')
        self.assertEqual(out['total_amount'], 500)
        # falls back to response_data for fields meta_data lacks
        self.assertEqual(out['gst_amount'], 90)

    def test_summary_reads_nested_payload(self):
        log = InvoiceExtractionLog(
            meta_data={'data': {'invoice_number': 'NEST-1', 'vendor_name': 'Acme'}},
            response_data=None,
        )
        out = extracted_summary(log)
        self.assertEqual(out['invoice_number'], 'NEST-1')
        self.assertEqual(out['vendor_name'], 'Acme')

    def test_vendor_pk_is_not_treated_as_a_name(self):
        """The pipeline writes `vendor` as a Vendor pk on some invoices."""
        out = extracted_summary(InvoiceExtractionLog(meta_data={'vendor': 20}))
        self.assertIsNone(out['vendor_name'])
        self.assertEqual(out['vendor_id'], 20)

        # numeric strings count as ids too
        out = extracted_summary(InvoiceExtractionLog(meta_data={'vendor': ' 20 '}))
        self.assertEqual(out['vendor_id'], 20)

        # a real name still comes through as a name
        out = extracted_summary(InvoiceExtractionLog(meta_data={'vendor': 'Acme Traders'}))
        self.assertEqual(out['vendor_name'], 'Acme Traders')
        self.assertIsNone(out['vendor_id'])

    def test_summary_handles_missing_payloads(self):
        out = extracted_summary(InvoiceExtractionLog())
        self.assertIsNone(out['invoice_number'])


class OcrJobsEndpointTest(TestCase):
    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.user = User.objects.create_user(username='ocruser', email='o@e.com', password='x')
        self.user.user_company = self.company
        self.user.is_company_admin = True
        self.user.save()

        give_plan(self.company,
                  ['purchases_invoice', 'ocr_purchase_invoice'],
                  limits={'ocr_purchase_invoice': {'ocr_scans_per_month': 25}})
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        admin_role.users.add(self.user)

        self.other_company = UserCompanies.objects.create(company_name='Rival', is_varified=True)
        self.rival = User.objects.create_user(username='rival', email='r@e.com', password='x')
        self.rival.user_company = self.other_company
        self.rival.save()

        InvoiceExtractionLog.objects.create(
            user=self.user, file='invoices/a.pdf', status='done',
            meta_data={'invoice_number': 'INV-1', 'total_final_amount': 1200})
        InvoiceExtractionLog.objects.create(
            user=self.user, file='invoices/b.pdf', status='Extraction Started')
        InvoiceExtractionLog.objects.create(
            user=self.rival, file='invoices/secret.pdf', status='done',
            meta_data={'invoice_number': 'SECRET'})

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_lists_company_jobs_only(self):
        res = self.client.get('/api/purchase/ocr-jobs/')
        self.assertEqual(res.status_code, 200, res.data)
        names = [j['file_name'] for j in res.data['jobs']]
        self.assertIn('a.pdf', names)
        self.assertIn('b.pdf', names)
        self.assertNotIn('secret.pdf', names)

    def test_counts_and_usage(self):
        res = self.client.get('/api/purchase/ocr-jobs/')
        self.assertEqual(res.data['counts']['completed'], 1)
        self.assertEqual(res.data['counts']['processing'], 1)
        self.assertEqual(res.data['usage']['total'], 2)
        self.assertEqual(res.data['usage']['this_month'], 2)
        self.assertEqual(res.data['usage']['daily_limit'], 10)

    def test_today_counts_by_local_date_not_utc(self):
        """A scan at 02:33 IST is 'today' even though its UTC date is yesterday.

        `timezone.now().date()` returns the UTC date while `created_at__date`
        converts to TIME_ZONE, so the two disagree for the first 5.5h of every
        IST day and 'today' silently read 0.
        """
        local_today = timezone.localdate()
        # 02:33 local == 21:03 UTC on the previous calendar day
        early = timezone.make_aware(
            datetime.combine(local_today, dt_time(2, 33)),
            timezone.get_current_timezone())
        self.assertNotEqual(early.astimezone(dt_timezone.utc).date(), local_today,
                            "fixture must land in the UTC/IST disagreement window")

        before = self.client.get('/api/purchase/ocr-jobs/').data['usage']['today']

        log = InvoiceExtractionLog.objects.create(
            user=self.user, file='invoices/early.pdf', status='done')
        # auto_now_add ignores any passed value, so backdate it explicitly
        InvoiceExtractionLog.objects.filter(pk=log.pk).update(created_at=early)

        after = self.client.get('/api/purchase/ocr-jobs/').data['usage']['today']
        self.assertEqual(after, before + 1,
                         "early-morning IST scan should count toward today")

    def test_vendor_pk_resolves_to_name(self):
        from companies.models import Vendor
        vendor = Vendor.objects.create(user=self.user, name='Acme Traders')
        InvoiceExtractionLog.objects.create(
            user=self.user, file='invoices/v.pdf', status='done',
            meta_data={'invoice_number': 'INV-V', 'vendor': vendor.id})

        res = self.client.get('/api/purchase/ocr-jobs/')
        job = next(j for j in res.data['jobs'] if j['file_name'] == 'v.pdf')
        self.assertEqual(job['extracted']['vendor_name'], 'Acme Traders')

    def test_state_filter(self):
        res = self.client.get('/api/purchase/ocr-jobs/?state=completed')
        self.assertEqual(len(res.data['jobs']), 1)
        self.assertEqual(res.data['jobs'][0]['extracted']['invoice_number'], 'INV-1')
        # counts stay whole-set even when the list is filtered
        self.assertEqual(res.data['counts']['processing'], 1)
