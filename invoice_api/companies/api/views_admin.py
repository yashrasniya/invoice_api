"""
Product Owner platform APIs (guarded by IsProductOwner).

    /api/admin/plans/                       GET POST
    /api/admin/plans/{id}/                  GET PUT PATCH DELETE
    /api/admin/plans/{id}/features/         GET POST      (attach feature + limits)
    /api/admin/plans/{id}/features/{fid}/   PUT DELETE    (edit limits / detach)
    /api/admin/features/                    GET POST
    /api/admin/features/{id}/               GET PUT PATCH DELETE
    /api/admin/companies/                   GET           (all tenants + subscription)
    /api/admin/companies/{id}/subscription/ GET POST PUT  (assign/change/cancel)
    /api/admin/audit-log/                   GET           (cross-tenant)
"""
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice_api.permissions import IsProductOwner

from accounts.models import AuditLog, UserCompanies
from accounts.api.serializers_authz import AuditLogSerializer
from companies.models import (CompanySubscription, Feature, PlanFeature,
                              SubscriptionPlan)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ['id', 'name', 'code', 'description', 'created_at']


class PlanFeatureSerializer(serializers.ModelSerializer):
    feature_code = serializers.CharField(source='feature.code', read_only=True)
    feature_name = serializers.CharField(source='feature.name', read_only=True)

    class Meta:
        model = PlanFeature
        fields = ['id', 'feature', 'feature_code', 'feature_name', 'limits']


class PlanSerializer(serializers.ModelSerializer):
    plan_features = PlanFeatureSerializer(many=True, read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = ['id', 'name', 'code', 'description', 'monthly_price',
                  'yearly_price', 'is_active', 'plan_features',
                  'created_at', 'updated_at']


class CompanySubscriptionSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source='subscription_plan.code', read_only=True)
    plan_name = serializers.CharField(source='subscription_plan.name', read_only=True)

    class Meta:
        model = CompanySubscription
        fields = ['id', 'company', 'subscription_plan', 'plan_code', 'plan_name',
                  'start_date', 'end_date', 'status', 'auto_renew',
                  'created_at', 'updated_at']
        read_only_fields = ['company']


class CompanyOverviewSerializer(serializers.ModelSerializer):
    active_subscription = serializers.SerializerMethodField()
    users_count = serializers.SerializerMethodField()

    class Meta:
        model = UserCompanies
        fields = ['id', 'company_name', 'company_email_id', 'state',
                  'is_varified', 'active_subscription', 'users_count']

    def get_active_subscription(self, obj):
        sub = (obj.company_subscriptions
               .filter(status__in=['active', 'trialing', 'past_due'])
               .order_by('-start_date').first())
        return CompanySubscriptionSerializer(sub).data if sub else None

    def get_users_count(self, obj):
        return obj.user_set.count()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class PlanViewSet(viewsets.ModelViewSet):
    serializer_class = PlanSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    queryset = SubscriptionPlan.objects.all().prefetch_related(
        'plan_features__feature').order_by('id')

    def perform_destroy(self, instance):
        if instance.company_subscriptions.filter(
                status__in=['active', 'trialing', 'past_due']).exists():
            raise ValidationError(
                "Plan has working subscriptions; deactivate it instead.")
        instance.delete()

    @action(detail=True, methods=['get', 'post'], url_path='features')
    def features(self, request, pk=None):
        plan = self.get_object()
        if request.method == 'GET':
            return Response(PlanFeatureSerializer(
                plan.plan_features.select_related('feature'), many=True).data)

        serializer = PlanFeatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pf, _ = PlanFeature.objects.update_or_create(
            subscription_plan=plan, feature=serializer.validated_data['feature'],
            defaults={'limits': serializer.validated_data.get('limits', {})})
        self._audit(request, plan, 'UPDATE', {'feature': pf.feature.code,
                                              'limits': pf.limits})
        return Response(PlanFeatureSerializer(pf).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['put', 'delete'],
            url_path='features/(?P<pf_id>[0-9]+)')
    def feature_detail(self, request, pk=None, pf_id=None):
        plan = self.get_object()
        try:
            pf = plan.plan_features.get(pk=pf_id)
        except PlanFeature.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if request.method == 'DELETE':
            self._audit(request, plan, 'DELETE', {'feature': pf.feature.code})
            pf.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        pf.limits = request.data.get('limits', pf.limits)
        pf.save()
        self._audit(request, plan, 'UPDATE', {'feature': pf.feature.code,
                                              'limits': pf.limits})
        return Response(PlanFeatureSerializer(pf).data)

    def _audit(self, request, plan, action_name, new_data):
        AuditLog.objects.create(
            company=None, user=request.user, action=action_name,
            resource_type='PLAN', resource_id=str(plan.id), new_data=new_data)


class FeatureViewSet(viewsets.ModelViewSet):
    serializer_class = FeatureSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    queryset = Feature.objects.all().order_by('code')


class CompanyListView(ListAPIView):
    serializer_class = CompanyOverviewSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    queryset = UserCompanies.objects.all().order_by('id')


class CompanySubscriptionAdminView(APIView):
    """Assign / change / cancel a tenant's subscription."""
    permission_classes = [IsAuthenticated, IsProductOwner]

    def _get_company(self, company_id):
        try:
            return UserCompanies.objects.get(pk=company_id)
        except UserCompanies.DoesNotExist:
            raise ValidationError("Company not found.")

    def get(self, request, company_id):
        company = self._get_company(company_id)
        subs = company.company_subscriptions.select_related(
            'subscription_plan').order_by('-start_date')
        return Response(CompanySubscriptionSerializer(subs, many=True).data)

    def post(self, request, company_id):
        """Assign a new subscription; supersedes any working one."""
        company = self._get_company(company_id)
        plan_id = request.data.get('subscription_plan')
        try:
            plan = SubscriptionPlan.objects.get(pk=plan_id, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            raise ValidationError("Active plan not found.")

        today = timezone.now().date()
        start = request.data.get('start_date') or today
        end = request.data.get('end_date') or (today + timedelta(days=365))
        new_status = request.data.get('status', 'active')
        if new_status not in ('active', 'trialing'):
            raise ValidationError("New subscriptions must be 'active' or 'trialing'.")

        # supersede current working subscription (unique constraint)
        (company.company_subscriptions
         .filter(status__in=['active', 'trialing'])
         .update(status='canceled'))

        sub = CompanySubscription.objects.create(
            company=company, subscription_plan=plan,
            start_date=start, end_date=end, status=new_status,
            auto_renew=request.data.get('auto_renew', True))
        cache.delete(f"company_sub:{company.id}")
        return Response(CompanySubscriptionSerializer(sub).data,
                        status=status.HTTP_201_CREATED)

    def put(self, request, company_id):
        """Update the current working subscription (extend / cancel / status)."""
        company = self._get_company(company_id)
        sub = (company.company_subscriptions
               .filter(status__in=['active', 'trialing', 'past_due'])
               .order_by('-start_date').first())
        if not sub:
            raise ValidationError("No working subscription to update.")

        for field in ('start_date', 'end_date', 'status', 'auto_renew'):
            if field in request.data:
                setattr(sub, field, request.data[field])
        if sub.status not in dict(CompanySubscription.STATUS_CHOICES):
            raise ValidationError("Invalid status.")
        sub.save()
        cache.delete(f"company_sub:{company.id}")
        return Response(CompanySubscriptionSerializer(sub).data)


class PlatformAuditLogView(ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get_queryset(self):
        qs = AuditLog.objects.all()
        company_id = self.request.query_params.get('company')
        if company_id:
            qs = qs.filter(company_id=company_id)
        return qs.select_related('user').order_by('-timestamp')[:1000]
