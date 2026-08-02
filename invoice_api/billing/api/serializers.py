from rest_framework import serializers

from companies.models import PlanFeature, SubscriptionPlan

from ..models import (BILLING_PERIOD_CHOICES, BillingSubscription,
                      PaymentRecord, RazorpayPlan, ScheduledPlanChange,
                      WebhookEvent)


class PlanFeatureBriefSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source='feature.code', read_only=True)
    name = serializers.CharField(source='feature.name', read_only=True)

    class Meta:
        model = PlanFeature
        fields = ['code', 'name', 'limits']


class PublicPlanSerializer(serializers.ModelSerializer):
    """Plan as shown on the billing page."""
    features = serializers.SerializerMethodField()
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = ['id', 'code', 'name', 'description', 'monthly_price',
                  'yearly_price', 'features', 'is_current']

    def get_features(self, obj):
        return PlanFeatureBriefSerializer(
            obj.plan_features.select_related('feature'), many=True).data

    def get_is_current(self, obj):
        return obj.id == self.context.get('current_plan_id')


class BillingSubscriptionSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source='subscription_plan.code', read_only=True)
    plan_name = serializers.CharField(source='subscription_plan.name', read_only=True)
    company_name = serializers.CharField(source='company.company_name', read_only=True)

    class Meta:
        model = BillingSubscription
        fields = ['id', 'company', 'company_name', 'plan_code', 'plan_name',
                  'period', 'razorpay_subscription_id', 'razorpay_customer_id',
                  'status', 'short_url', 'current_start', 'current_end',
                  'charge_at', 'paid_count', 'total_count',
                  'cancel_at_cycle_end', 'last_synced_at', 'created_at']
        read_only_fields = fields


class ScheduledPlanChangeSerializer(serializers.ModelSerializer):
    from_plan_code = serializers.CharField(source='from_plan.code', read_only=True)
    to_plan_code = serializers.CharField(source='to_plan.code', read_only=True)
    to_plan_name = serializers.CharField(source='to_plan.name', read_only=True)

    class Meta:
        model = ScheduledPlanChange
        fields = ['id', 'from_plan_code', 'to_plan_code', 'to_plan_name',
                  'period', 'effective_date', 'status', 'applied_at', 'created_at']
        read_only_fields = fields


class PaymentRecordSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source='subscription_plan.code',
                                      read_only=True, default=None)
    amount = serializers.DecimalField(source='amount_rupees', max_digits=12,
                                      decimal_places=2, read_only=True)
    company_name = serializers.CharField(source='company.company_name', read_only=True)

    class Meta:
        model = PaymentRecord
        fields = ['id', 'company', 'company_name', 'razorpay_payment_id',
                  'razorpay_invoice_id', 'amount', 'currency', 'status',
                  'method', 'description', 'error_description', 'plan_code',
                  'paid_at', 'created_at']
        read_only_fields = fields


class RazorpayPlanSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source='subscription_plan.code', read_only=True)
    is_stale = serializers.BooleanField(read_only=True)

    class Meta:
        model = RazorpayPlan
        fields = ['id', 'plan_code', 'period', 'razorpay_plan_id',
                  'amount_paise', 'currency', 'is_active', 'is_stale',
                  'created_at']
        read_only_fields = fields


class WebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEvent
        fields = ['id', 'event_id', 'event', 'status', 'error', 'company',
                  'received_at', 'processed_at']
        read_only_fields = fields


# --- request serializers ---------------------------------------------------

class PlanSelectionSerializer(serializers.Serializer):
    """Note what is NOT here: any amount. Prices come from the database only."""
    plan_code = serializers.CharField(max_length=100)
    period = serializers.ChoiceField(choices=BILLING_PERIOD_CHOICES)


class CheckoutVerifySerializer(serializers.Serializer):
    razorpay_payment_id = serializers.CharField(max_length=64)
    razorpay_subscription_id = serializers.CharField(max_length=64)
    razorpay_signature = serializers.CharField(max_length=256)


class CancelSerializer(serializers.Serializer):
    at_cycle_end = serializers.BooleanField(default=True)
