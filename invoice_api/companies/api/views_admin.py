"""
Product Owner platform APIs (guarded by IsProductOwner).

    /api/admin/overview/                    GET           (platform KPIs + needs-attention counts)
    /api/admin/plans/                       GET POST
    /api/admin/plans/{id}/                  GET PUT PATCH DELETE
    /api/admin/plans/{id}/features/         GET POST      (attach feature + limits)
    /api/admin/plans/{id}/features/{fid}/   PUT DELETE    (edit limits / detach)
    /api/admin/features/                    GET POST
    /api/admin/features/{id}/               GET PUT PATCH DELETE (?force=1 to delete a feature in use)
    /api/admin/companies/                   GET           (paginated; ?search= ?plan= ?status= ?ending_within= ?ordering=)
    /api/admin/companies/{id}/subscription/ GET POST PUT  (history / assign / extend-cancel)
    /api/admin/audit-log/                   GET           (paginated; ?company= ?resource_type= ?action= ?user= ?date_from= ?date_to=)
    /api/admin/whatsapp-account/            GET PUT
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice_api.pagination import AdminPagination
from invoice_api.permissions import IsProductOwner

from accounts.models import AuditLog, User, UserCompanies
from accounts.api.serializers_authz import AuditLogSerializer
from companies.models import (CompanySubscription, Feature, PlanFeature,
                              SubscriptionPlan)

# Statuses that give a company access (mirrors CompanyOverviewSerializer).
WORKING_STATUSES = ('active', 'trialing', 'past_due')


def _jsonable(value):
    if isinstance(value, (date, Decimal)):
        return str(value)
    return value


def _sub_snapshot(sub):
    return {
        'plan': sub.subscription_plan.code,
        'status': sub.status,
        'start_date': _jsonable(sub.start_date),
        'end_date': _jsonable(sub.end_date),
        'auto_renew': sub.auto_renew,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class FeatureSerializer(serializers.ModelSerializer):
    plans = serializers.SerializerMethodField()

    class Meta:
        model = Feature
        fields = ['id', 'name', 'code', 'description', 'plans', 'created_at']

    def get_plans(self, obj):
        return [pf.subscription_plan.code for pf in obj.plan_features.all()]

    def validate_code(self, value):
        # code is the stable key used by gates; it can't change after create
        if self.instance and value != self.instance.code:
            raise ValidationError("Feature code can't be changed.")
        return value


class PlanFeatureSerializer(serializers.ModelSerializer):
    feature_code = serializers.CharField(source='feature.code', read_only=True)
    feature_name = serializers.CharField(source='feature.name', read_only=True)

    class Meta:
        model = PlanFeature
        fields = ['id', 'feature', 'feature_code', 'feature_name', 'limits']

    def validate_limits(self, value):
        if not isinstance(value, dict):
            raise ValidationError("Limits must be a JSON object.")
        return value


class PlanSerializer(serializers.ModelSerializer):
    plan_features = PlanFeatureSerializer(many=True, read_only=True)
    subscriber_count = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = ['id', 'name', 'code', 'description', 'monthly_price',
                  'yearly_price', 'is_active', 'plan_features',
                  'subscriber_count', 'created_at', 'updated_at']

    def get_subscriber_count(self, obj):
        annotated = getattr(obj, 'subscriber_count', None)
        if annotated is not None:
            return annotated
        return obj.company_subscriptions.filter(status__in=WORKING_STATUSES).count()


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
    users_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = UserCompanies
        fields = ['id', 'company_name', 'company_email_id', 'company_phone',
                  'city', 'state', 'company_gst_number', 'is_varified',
                  'trial_used_at', 'active_subscription', 'users_count']

    def get_active_subscription(self, obj):
        # `working_subs` is prefetched newest-first by CompanyListView
        subs = getattr(obj, 'working_subs', None)
        if subs is None:
            sub = (obj.company_subscriptions
                   .filter(status__in=WORKING_STATUSES)
                   .order_by('-start_date').first())
        else:
            sub = subs[0] if subs else None
        return CompanySubscriptionSerializer(sub).data if sub else None


class PlatformAuditLogSerializer(AuditLogSerializer):
    company_name = serializers.CharField(source='company.company_name',
                                         read_only=True, default=None)

    class Meta(AuditLogSerializer.Meta):
        fields = AuditLogSerializer.Meta.fields + ['company', 'company_name']


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class PlatformOverviewView(APIView):
    """GET /api/admin/overview/ — one call for the admin landing tab."""
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get(self, request):
        today = timezone.localdate()
        working = (CompanySubscription.objects
                   .filter(status__in=WORKING_STATUSES)
                   .select_related('subscription_plan'))

        by_status = {s: 0 for s in WORKING_STATUSES}
        for row in working.values('status').annotate(n=Count('id')):
            by_status[row['status']] = row['n']

        companies_total = UserCompanies.objects.count()
        with_plan = working.values('company_id').distinct().count()

        # MRR estimate: paying subs only (not trials), at the plan's monthly price
        mrr = sum((s.subscription_plan.monthly_price or Decimal('0'))
                  for s in working.filter(status__in=('active', 'past_due')))

        plans = (SubscriptionPlan.objects
                 .annotate(n=Count('company_subscriptions', filter=Q(
                     company_subscriptions__status__in=WORKING_STATUSES)))
                 .order_by('-n', 'id'))

        try:
            from billing.api.views_admin import billing_health
            billing = billing_health()
        except Exception:  # billing app misconfigured must not break overview
            billing = None

        return Response({
            'companies': companies_total,
            'users': User.objects.filter(user_company__isnull=False).count(),
            'signups_30d': User.objects.filter(
                date_joined__gte=timezone.now() - timedelta(days=30)).count(),
            'subscriptions': {**by_status,
                              'none': max(companies_total - with_plan, 0)},
            'trials_ending_7d': working.filter(
                status='trialing', end_date__lte=today + timedelta(days=7)).count(),
            'subs_ending_30d': working.filter(
                status__in=('active', 'past_due'),
                end_date__lte=today + timedelta(days=30)).count(),
            'mrr_estimate': str(mrr),
            'plans': [{'id': p.id, 'code': p.code, 'name': p.name,
                       'is_active': p.is_active, 'subscribers': p.n}
                      for p in plans],
            'billing': billing,
        })


class PlanViewSet(viewsets.ModelViewSet):
    serializer_class = PlanSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get_queryset(self):
        return (SubscriptionPlan.objects
                .prefetch_related('plan_features__feature')
                .annotate(subscriber_count=Count(
                    'company_subscriptions',
                    filter=Q(company_subscriptions__status__in=WORKING_STATUSES)))
                .order_by('id'))

    def perform_destroy(self, instance):
        if instance.company_subscriptions.filter(
                status__in=WORKING_STATUSES).exists():
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
        limits = request.data.get('limits', pf.limits)
        if not isinstance(limits, dict):
            raise ValidationError({'limits': 'Limits must be a JSON object.'})
        previous = pf.limits
        pf.limits = limits
        pf.save()
        self._audit(request, plan, 'UPDATE', {'feature': pf.feature.code,
                                              'limits': pf.limits},
                    previous={'feature': pf.feature.code, 'limits': previous})
        return Response(PlanFeatureSerializer(pf).data)

    def _audit(self, request, plan, action_name, new_data, previous=None):
        AuditLog.objects.create(
            company=None, user=request.user, action=action_name,
            resource_type='PLAN', resource_id=str(plan.id),
            previous_data=previous, new_data=new_data)


class FeatureViewSet(viewsets.ModelViewSet):
    serializer_class = FeatureSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    queryset = (Feature.objects
                .prefetch_related('plan_features__subscription_plan')
                .order_by('code'))

    def destroy(self, request, *args, **kwargs):
        feature = self.get_object()
        plan_codes = [pf.subscription_plan.code for pf in feature.plan_features.all()]
        if plan_codes and request.query_params.get('force') != '1':
            return Response(
                {'detail': f"Feature is attached to {len(plan_codes)} plan(s): "
                           f"{', '.join(plan_codes)}. Pass force=1 to delete anyway.",
                 'plans': plan_codes},
                status=status.HTTP_400_BAD_REQUEST)
        AuditLog.objects.create(
            company=None, user=request.user, action='DELETE',
            resource_type='FEATURE', resource_id=str(feature.id),
            previous_data={'code': feature.code, 'plans': plan_codes})
        feature.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompanyListView(ListAPIView):
    serializer_class = CompanyOverviewSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    pagination_class = AdminPagination

    ORDERINGS = {
        'id': 'id', '-id': '-id',
        'name': 'company_name', '-name': '-company_name',
        'users': 'users_count', '-users': '-users_count',
    }

    def get_queryset(self):
        params = self.request.query_params
        working_qs = (CompanySubscription.objects
                      .filter(status__in=WORKING_STATUSES)
                      .select_related('subscription_plan')
                      .order_by('-start_date'))
        qs = (UserCompanies.objects
              .annotate(users_count=Count('user', distinct=True))
              .prefetch_related(Prefetch('company_subscriptions',
                                         queryset=working_qs,
                                         to_attr='working_subs')))

        search = (params.get('search') or '').strip()
        if search:
            q = (Q(company_name__icontains=search) |
                 Q(company_email_id__icontains=search) |
                 Q(company_phone__icontains=search) |
                 Q(company_gst_number__icontains=search))
            if search.isdigit():
                q |= Q(pk=int(search))
            qs = qs.filter(q)

        working_filter = Q(company_subscriptions__status__in=WORKING_STATUSES)
        plan = params.get('plan')
        if plan:
            qs = qs.filter(working_filter,
                           company_subscriptions__subscription_plan__code=plan)

        sub_status = params.get('status')
        if sub_status == 'none':
            qs = qs.exclude(company_subscriptions__status__in=WORKING_STATUSES)
        elif sub_status in WORKING_STATUSES:
            qs = qs.filter(company_subscriptions__status=sub_status)

        ending = params.get('ending_within')
        if ending and ending.isdigit():
            cutoff = timezone.localdate() + timedelta(days=int(ending))
            qs = qs.filter(working_filter,
                           company_subscriptions__end_date__lte=cutoff)

        ordering = self.ORDERINGS.get(params.get('ordering') or '-id', '-id')
        return qs.distinct().order_by(ordering, 'id')


class CompanySubscriptionAdminView(APIView):
    """Assign / change / cancel a tenant's subscription."""
    permission_classes = [IsAuthenticated, IsProductOwner]

    def _get_company(self, company_id):
        try:
            return UserCompanies.objects.get(pk=company_id)
        except UserCompanies.DoesNotExist:
            raise ValidationError("Company not found.")

    def _audit(self, request, company, sub, action_name, previous=None):
        AuditLog.objects.create(
            company=company, user=request.user, action=action_name,
            resource_type='SUBSCRIPTION', resource_id=str(sub.id),
            previous_data=previous,
            new_data={**_sub_snapshot(sub), 'via': 'platform_admin'})

    def get(self, request, company_id):
        company = self._get_company(company_id)
        subs = company.company_subscriptions.select_related(
            'subscription_plan').order_by('-start_date', '-id')
        return Response(CompanySubscriptionSerializer(subs, many=True).data)

    def post(self, request, company_id):
        """Assign a new subscription; supersedes any working one."""
        company = self._get_company(company_id)
        plan_id = request.data.get('subscription_plan')
        try:
            plan = SubscriptionPlan.objects.get(pk=plan_id, is_active=True)
        except (SubscriptionPlan.DoesNotExist, ValueError, TypeError):
            raise ValidationError("Active plan not found.")

        today = timezone.localdate()
        start = request.data.get('start_date') or today
        end = request.data.get('end_date') or (today + timedelta(days=365))
        new_status = request.data.get('status', 'active')
        if new_status not in ('active', 'trialing'):
            raise ValidationError("New subscriptions must be 'active' or 'trialing'.")

        previous = (company.company_subscriptions
                    .filter(status__in=['active', 'trialing'])
                    .select_related('subscription_plan')
                    .order_by('-start_date').first())
        previous_data = _sub_snapshot(previous) if previous else None

        # supersede current working subscription (unique constraint)
        (company.company_subscriptions
         .filter(status__in=['active', 'trialing'])
         .update(status='canceled'))

        sub = CompanySubscription.objects.create(
            company=company, subscription_plan=plan,
            start_date=start, end_date=end, status=new_status,
            auto_renew=request.data.get('auto_renew', True))
        sub.refresh_from_db()
        cache.delete(f"company_sub:{company.id}")
        self._audit(request, company, sub, 'ASSIGN', previous_data)
        return Response(CompanySubscriptionSerializer(sub).data,
                        status=status.HTTP_201_CREATED)

    def put(self, request, company_id):
        """Update the current working subscription (extend / cancel / status)."""
        company = self._get_company(company_id)
        sub = (company.company_subscriptions
               .filter(status__in=WORKING_STATUSES)
               .select_related('subscription_plan')
               .order_by('-start_date').first())
        if not sub:
            raise ValidationError("No working subscription to update.")

        previous = _sub_snapshot(sub)
        for field in ('start_date', 'end_date', 'status', 'auto_renew'):
            if field in request.data:
                setattr(sub, field, request.data[field])
        if sub.status not in dict(CompanySubscription.STATUS_CHOICES):
            raise ValidationError("Invalid status.")
        for field in ('start_date', 'end_date'):
            value = getattr(sub, field)
            if isinstance(value, str):
                parsed = parse_date(value)
                if not parsed:
                    raise ValidationError({field: 'Use YYYY-MM-DD.'})
                setattr(sub, field, parsed)
        if sub.end_date < sub.start_date:
            raise ValidationError({'end_date': 'End date is before start date.'})
        sub.save()
        cache.delete(f"company_sub:{company.id}")
        self._audit(request, company, sub, 'UPDATE', previous)
        return Response(CompanySubscriptionSerializer(sub).data)


class PlatformWhatsAppAccountView(APIView):
    """Product Owner: manage the shared WhatsApp account & default limit.
    GET returns details with the access token masked; PUT updates fields
    (token only replaced when a non-empty value is sent)."""
    permission_classes = [IsAuthenticated, IsProductOwner]

    FIELDS = ['name', 'business_account_id', 'phone_number_id',
              'default_template_name', 'is_active', 'default_daily_limit']

    def _serialize(self, acct):
        data = {f: getattr(acct, f) for f in self.FIELDS}
        data['id'] = acct.id
        token = acct.access_token or ''
        data['access_token_masked'] = f"…{token[-6:]}" if token else None
        data['has_access_token'] = bool(token)
        return data

    def get(self, request):
        from whatsapp_integration.models import PlatformWhatsAppAccount
        acct = (PlatformWhatsAppAccount.objects.order_by('id').first() or
                PlatformWhatsAppAccount.objects.create(name='Default account'))
        return Response(self._serialize(acct))

    def put(self, request):
        from whatsapp_integration.models import PlatformWhatsAppAccount
        acct = (PlatformWhatsAppAccount.objects.order_by('id').first() or
                PlatformWhatsAppAccount.objects.create(name='Default account'))
        for f in self.FIELDS:
            if f in request.data:
                setattr(acct, f, request.data[f])
        if request.data.get('access_token'):
            acct.access_token = request.data['access_token']
        try:
            acct.default_daily_limit = int(acct.default_daily_limit)
        except (TypeError, ValueError):
            raise ValidationError({'default_daily_limit': 'Must be a number.'})
        acct.save()
        AuditLog.objects.create(
            company=None, user=request.user, action='UPDATE',
            resource_type='WHATSAPP_ACCOUNT', resource_id=str(acct.id),
            new_data={'name': acct.name, 'is_active': acct.is_active,
                      'default_daily_limit': acct.default_daily_limit})
        return Response(self._serialize(acct))


class PlatformAuditLogView(ListAPIView):
    serializer_class = PlatformAuditLogSerializer
    permission_classes = [IsAuthenticated, IsProductOwner]
    pagination_class = AdminPagination

    def get_queryset(self):
        params = self.request.query_params
        qs = AuditLog.objects.select_related('user', 'company')
        if params.get('company'):
            qs = qs.filter(company_id=params['company'])
        if params.get('resource_type'):
            qs = qs.filter(resource_type=params['resource_type'])
        if params.get('action'):
            qs = qs.filter(action=params['action'])
        if params.get('user'):
            qs = qs.filter(user__username__icontains=params['user'])
        for param, lookup in (('date_from', 'timestamp__date__gte'),
                              ('date_to', 'timestamp__date__lte')):
            if params.get(param):
                parsed = parse_date(params[param])
                if not parsed:
                    raise ValidationError({param: 'Use YYYY-MM-DD.'})
                qs = qs.filter(**{lookup: parsed})
        return qs.order_by('-timestamp', '-id')


class PlatformAuditFacetsView(APIView):
    """GET /api/admin/audit-log/facets/ — distinct resource types & actions
    for the audit filter dropdowns."""
    permission_classes = [IsAuthenticated, IsProductOwner]

    def get(self, request):
        return Response({
            'resource_types': sorted(set(AuditLog.objects.values_list(
                'resource_type', flat=True).distinct())),
            'actions': sorted(set(AuditLog.objects.values_list(
                'action', flat=True).distinct())),
        })
