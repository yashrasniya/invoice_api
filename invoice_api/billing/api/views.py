"""Tenant-facing billing endpoints.

Every view resolves the company from `request.company` (set by the tenant
middleware after membership validation) — never from a request body or URL
parameter. There is no endpoint here that takes a company id.
"""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from companies.models import CompanySubscription, SubscriptionPlan
from invoice_api.permissions import HasPermission

from .. import services
from ..models import BillingSubscription, PaymentRecord, ScheduledPlanChange
from ..razorpay_client import (BillingUnavailable, RazorpayNotConfigured,
                               is_test_mode,
                               verify_subscription_payment_signature)
from .serializers import (BillingSubscriptionSerializer, CancelSerializer,
                          CheckoutVerifySerializer, PaymentRecordSerializer,
                          PlanSelectionSerializer, PublicPlanSerializer,
                          ScheduledPlanChangeSerializer)

logger = logging.getLogger('billing')

ViewBilling = HasPermission.with_code('subscription.view')
ManageBilling = HasPermission.with_code('subscription.manage')


class _CompanyMixin:
    def get_company(self):
        company = getattr(self.request, 'company', None)
        if company is None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("No company context for this user.")
        return company


class BillingPlansView(_CompanyMixin, APIView):
    """GET /api/billing/plans/ — plans, prices and features for the pricing UI."""
    permission_classes = [IsAuthenticated, ViewBilling]

    def get(self, request):
        company = self.get_company()
        entitlement = (CompanySubscription.objects
                       .filter(company=company)
                       .select_related('subscription_plan')
                       .order_by('-start_date').first())
        plans = (SubscriptionPlan.objects.filter(is_active=True)
                 .prefetch_related('plan_features__feature')
                 .order_by('monthly_price', 'id'))
        return Response({
            'plans': PublicPlanSerializer(
                plans, many=True,
                context={'current_plan_id': entitlement.subscription_plan_id
                         if entitlement else None}).data,
            'currency': 'INR',
        })


class BillingStatusView(_CompanyMixin, APIView):
    """GET /api/billing/subscription/ — everything the billing page needs."""
    permission_classes = [IsAuthenticated, ViewBilling]

    def get(self, request):
        company = self.get_company()
        entitlement = (CompanySubscription.objects
                       .filter(company=company)
                       .select_related('subscription_plan')
                       .order_by('-start_date').first())
        live = services.get_live_subscription(company)
        pending = ScheduledPlanChange.objects.filter(
            company=company, status='pending').select_related(
            'to_plan', 'from_plan').first()

        return Response({
            'entitlement': {
                'plan_code': entitlement.subscription_plan.code if entitlement else None,
                'plan_name': entitlement.subscription_plan.name if entitlement else None,
                'status': entitlement.status if entitlement else None,
                'start_date': entitlement.start_date if entitlement else None,
                'end_date': entitlement.end_date if entitlement else None,
                'auto_renew': entitlement.auto_renew if entitlement else False,
                'is_working': entitlement.is_working() if entitlement else False,
            } if entitlement else None,
            'billing_subscription': BillingSubscriptionSerializer(live).data if live else None,
            'scheduled_change': ScheduledPlanChangeSerializer(pending).data if pending else None,
            'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', ''),
            'test_mode': is_test_mode(),
        })


class BillingPreviewView(_CompanyMixin, APIView):
    """GET /api/billing/preview/?plan_code=pro&period=monthly"""
    permission_classes = [IsAuthenticated, ViewBilling]

    def get(self, request):
        plan_code = request.query_params.get('plan_code')
        period = request.query_params.get('period', 'monthly')
        if not plan_code:
            return Response({'plan_code': 'This query parameter is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(services.proration_preview(
            self.get_company(), plan_code, period))


class SubscribeView(_CompanyMixin, APIView):
    """POST /api/billing/subscribe/ {plan_code, period}

    Creates the Razorpay subscription and returns what Checkout needs.
    Grants nothing — entitlement waits for `subscription.activated`.
    """
    permission_classes = [IsAuthenticated, ManageBilling]

    def post(self, request):
        serializer = PlanSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = self.get_company()

        try:
            print(company.company_email_id,serializer.validated_data['plan_code'],serializer.validated_data['period'])
            sub = services.start_subscription(
                company,
                serializer.validated_data['plan_code'],
                serializer.validated_data['period'],
                user=request.user)
        except RazorpayNotConfigured as exc:
            print(exc)
            return Response({'detail': str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except BillingUnavailable as exc:
            # Razorpay said no. Surface why, with the right status, instead of
            # letting the SDK exception become a 500 traceback.
            logger.warning("billing: %s", exc)
            return Response({'detail': str(exc), 'retryable': exc.retryable},
                            status=exc.status_code)

        return Response({
            'subscription_id': sub.razorpay_subscription_id,
            'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', ''),
            'short_url': sub.short_url,
            'plan_code': sub.subscription_plan.code,
            'plan_name': sub.subscription_plan.name,
            'period': sub.period,
            'prefill': {
                'name': (company.company_name or '')[:100],
                'email': company.company_email_id or request.user.email or '',
            },
            'test_mode': is_test_mode(),
        }, status=status.HTTP_201_CREATED)


class CheckoutVerifyView(_CompanyMixin, APIView):
    """POST /api/billing/verify/

    The browser posts back what Checkout handed it. We verify the signature to
    confirm the callback is genuine, then pull authoritative state from
    Razorpay. This exists purely so the UI updates immediately rather than
    waiting for the webhook — the webhook remains the source of truth.
    """
    permission_classes = [IsAuthenticated, ManageBilling]

    def post(self, request):
        serializer = CheckoutVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        company = self.get_company()

        sub = BillingSubscription.objects.filter(
            company=company,
            razorpay_subscription_id=data['razorpay_subscription_id']).first()
        if not sub:
            # Do not leak whether the id exists under another tenant.
            return Response({'detail': 'Unknown subscription for this company.'},
                            status=status.HTTP_404_NOT_FOUND)

        if not verify_subscription_payment_signature(
                data['razorpay_subscription_id'],
                data['razorpay_payment_id'],
                data['razorpay_signature']):
            logger.warning("billing: bad checkout signature for %s (company=%s)",
                           data['razorpay_subscription_id'], company.id)
            return Response({'detail': 'Payment signature verification failed.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            services.sync_subscription(sub)
        except Exception:
            logger.exception("billing: post-checkout sync failed for %s",
                             sub.razorpay_subscription_id)
            # The webhook will still settle this; don't fail the user's page.
            return Response({'status': 'pending',
                             'detail': 'Payment received. Activation in progress.'},
                            status=status.HTTP_202_ACCEPTED)

        sub.refresh_from_db()
        return Response({'status': 'ok',
                         'subscription': BillingSubscriptionSerializer(sub).data})


class ChangePlanView(_CompanyMixin, APIView):
    """POST /api/billing/change-plan/ {plan_code, period}"""
    permission_classes = [IsAuthenticated, ManageBilling]

    def post(self, request):
        serializer = PlanSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = self.get_company()

        try:
            result = services.change_plan(
                company,
                serializer.validated_data['plan_code'],
                serializer.validated_data['period'],
                user=request.user)
        except RazorpayNotConfigured as exc:
            return Response({'detail': str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except BillingUnavailable as exc:
            # Razorpay said no. Surface why, with the right status, instead of
            # letting the SDK exception become a 500 traceback.
            logger.warning("billing: %s", exc)
            return Response({'detail': str(exc), 'retryable': exc.retryable},
                            status=exc.status_code)

        response = {'effect': result['effect'],
                    'requires_checkout': result.get('requires_checkout', False)}
        if result.get('effective_date'):
            response['effective_date'] = result['effective_date']
        sub = result.get('subscription')
        if sub is not None:
            response.update({
                'subscription_id': sub.razorpay_subscription_id,
                'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', ''),
                'short_url': sub.short_url,
                'plan_code': sub.subscription_plan.code,
                'period': sub.period,
                'prefill': {
                    'name': (company.company_name or '')[:100],
                    'email': company.company_email_id or request.user.email or '',
                },
            })
        return Response(response)


class CancelSubscriptionView(_CompanyMixin, APIView):
    """POST /api/billing/cancel/ {at_cycle_end}"""
    permission_classes = [IsAuthenticated, ManageBilling]

    def post(self, request):
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sub = services.cancel_subscription(
                self.get_company(),
                at_cycle_end=serializer.validated_data['at_cycle_end'],
                user=request.user)
        except RazorpayNotConfigured as exc:
            return Response({'detail': str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except BillingUnavailable as exc:
            # Razorpay said no. Surface why, with the right status, instead of
            # letting the SDK exception become a 500 traceback.
            logger.warning("billing: %s", exc)
            return Response({'detail': str(exc), 'retryable': exc.retryable},
                            status=exc.status_code)
        return Response({'status': 'cancelled',
                         'at_cycle_end': sub.cancel_at_cycle_end,
                         'subscription': BillingSubscriptionSerializer(sub).data})


class PaymentHistoryView(_CompanyMixin, ListAPIView):
    """GET /api/billing/payments/ — this company's payments only."""
    serializer_class = PaymentRecordSerializer
    permission_classes = [IsAuthenticated, ViewBilling]

    def get_queryset(self):
        return (PaymentRecord.objects
                .filter(company=self.get_company())
                .select_related('subscription_plan', 'company')
                .order_by('-paid_at', '-created_at'))
