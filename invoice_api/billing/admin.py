from django.contrib import admin

from .models import (BillingSubscription, PaymentRecord, RazorpayPlan,
                     ScheduledPlanChange, WebhookEvent)


@admin.register(RazorpayPlan)
class RazorpayPlanAdmin(admin.ModelAdmin):
    list_display = ('subscription_plan', 'period', 'razorpay_plan_id',
                    'amount_paise', 'is_active', 'created_at')
    list_filter = ('period', 'is_active')
    search_fields = ('razorpay_plan_id', 'subscription_plan__code')


@admin.register(BillingSubscription)
class BillingSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('company', 'subscription_plan', 'period', 'status',
                    'current_end', 'cancel_at_cycle_end', 'created_at')
    list_filter = ('status', 'period', 'cancel_at_cycle_end')
    search_fields = ('razorpay_subscription_id', 'razorpay_customer_id',
                     'company__company_name')
    readonly_fields = ('razorpay_subscription_id', 'razorpay_customer_id',
                       'created_at', 'updated_at')


@admin.register(ScheduledPlanChange)
class ScheduledPlanChangeAdmin(admin.ModelAdmin):
    list_display = ('company', 'from_plan', 'to_plan', 'effective_date',
                    'status', 'applied_at')
    list_filter = ('status', 'period')


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ('razorpay_payment_id', 'company', 'amount_rupees',
                    'status', 'method', 'paid_at')
    list_filter = ('status', 'method', 'currency')
    search_fields = ('razorpay_payment_id', 'razorpay_invoice_id',
                     'company__company_name')
    readonly_fields = ('raw',)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event', 'event_id', 'status', 'company', 'received_at',
                    'processed_at')
    list_filter = ('status', 'event')
    search_fields = ('event_id', 'event')
    readonly_fields = ('payload',)
