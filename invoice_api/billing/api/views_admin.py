"""Product Owner billing tools. All views are IsProductOwner."""
import logging

from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice_api.permissions import IsProductOwner

from .. import services
from ..models import (BillingSubscription, PaymentRecord, RazorpayPlan,
                      ScheduledPlanChange, WebhookEvent)
from ..razorpay_client import (BillingUnavailable, RazorpayNotConfigured,
                               is_test_mode)
from .serializers import (BillingSubscriptionSerializer,
                          PaymentRecordSerializer, RazorpayPlanSerializer,
                          ScheduledPlanChangeSerializer,
                          WebhookEventSerializer)

logger = logging.getLogger('billing')


class AdminSyncPlansView(APIView):
    """POST /api/admin/billing/sync-plans/ — push local plans to Razorpay."""
    permission_classes = [IsAuthenticated, IsProductOwner]

    def post(self, request):
        try:
            report = services.sync_all_plans()
        except RazorpayNotConfigured as exc:
            return Response({'detail': str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except BillingUnavailable as exc:
            return Response({'detail': str(exc), 'retryable': exc.retryable},
                            status=exc.status_code)
        return Response({'results': [
            {'plan_code': c, 'period': p, 'result': r} for c, p, r in report]})


class AdminRazorpayPlanListView(ListAPIView):
    serializer_class = RazorpayPlanSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    queryset = (RazorpayPlan.objects.select_related('subscription_plan')
                .order_by('subscription_plan__id', 'period'))


class AdminSubscriptionListView(ListAPIView):
    serializer_class = BillingSubscriptionSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get_queryset(self):
        qs = (BillingSubscription.objects
              .select_related('subscription_plan', 'company')
              .order_by('-created_at'))
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        company_id = self.request.query_params.get('company_id')
        if company_id:
            qs = qs.filter(company_id=company_id)
        return qs


class AdminReconcileView(APIView):
    """POST /api/admin/billing/subscriptions/<pk>/reconcile/

    Re-fetch from Razorpay and re-apply. The manual escape hatch for when a
    webhook was missed or arrived out of order.
    """
    permission_classes = [IsAuthenticated, IsProductOwner]

    def post(self, request, pk):
        sub = BillingSubscription.objects.filter(pk=pk).first()
        if not sub:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            services.sync_subscription(sub)
        except RazorpayNotConfigured as exc:
            return Response({'detail': str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except BillingUnavailable as exc:
            return Response({'detail': str(exc), 'retryable': exc.retryable},
                            status=exc.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.exception("billing: reconcile failed for %s", pk)
            return Response({'detail': str(exc)},
                            status=status.HTTP_502_BAD_GATEWAY)
        sub.refresh_from_db()
        return Response(BillingSubscriptionSerializer(sub).data)


class AdminPaymentListView(ListAPIView):
    serializer_class = PaymentRecordSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get_queryset(self):
        qs = (PaymentRecord.objects
              .select_related('company', 'subscription_plan')
              .order_by('-paid_at', '-created_at'))
        company_id = self.request.query_params.get('company_id')
        if company_id:
            qs = qs.filter(company_id=company_id)
        payment_status = self.request.query_params.get('status')
        if payment_status:
            qs = qs.filter(status=payment_status)
        return qs


class AdminWebhookEventListView(ListAPIView):
    serializer_class = WebhookEventSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get_queryset(self):
        qs = WebhookEvent.objects.order_by('-received_at')
        event_status = self.request.query_params.get('status')
        if event_status:
            qs = qs.filter(status=event_status)
        return qs


class AdminScheduledChangeListView(ListAPIView):
    serializer_class = ScheduledPlanChangeSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    queryset = (ScheduledPlanChange.objects
                .select_related('from_plan', 'to_plan', 'company')
                .order_by('-created_at'))


class AdminApplyScheduledChangesView(APIView):
    """POST /api/admin/billing/apply-scheduled/ — run the downgrade job now."""
    permission_classes = [IsAuthenticated, IsProductOwner]

    def post(self, request):
        applied = services.apply_due_scheduled_changes()
        return Response({'applied': len(applied),
                         'changes': ScheduledPlanChangeSerializer(applied, many=True).data})


class AdminBillingHealthView(APIView):
    """GET /api/admin/billing/health/ — is billing wired up correctly?"""
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get(self, request):
        from django.conf import settings
        stale = [p.razorpay_plan_id for p in RazorpayPlan.objects.filter(
            is_active=True).select_related('subscription_plan') if p.is_stale]
        return Response({
            'key_id_configured': bool(getattr(settings, 'RAZORPAY_KEY_ID', '')),
            'key_secret_configured': bool(getattr(settings, 'RAZORPAY_KEY_SECRET', '')),
            'webhook_secret_configured': bool(
                getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')),
            'test_mode': is_test_mode(),
            'razorpay_plans': RazorpayPlan.objects.filter(is_active=True).count(),
            'stale_plans': stale,
            'live_subscriptions': BillingSubscription.objects.filter(
                status__in=BillingSubscription.LIVE_STATUSES).count(),
            'failed_webhooks': WebhookEvent.objects.filter(status='failed').count(),
            'pending_scheduled_changes': ScheduledPlanChange.objects.filter(
                status='pending').count(),
        })
