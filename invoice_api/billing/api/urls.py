from django.urls import path

from ..webhooks import RazorpayWebhookView
from . import views, views_admin

urlpatterns = [
    # --- webhook (unauthenticated, signature-verified) -------------------
    path('billing/webhook/razorpay/', RazorpayWebhookView.as_view(),
         name='razorpay-webhook'),

    # --- tenant ----------------------------------------------------------
    path('billing/plans/', views.BillingPlansView.as_view()),
    path('billing/subscription/', views.BillingStatusView.as_view()),
    path('billing/preview/', views.BillingPreviewView.as_view()),
    path('billing/subscribe/', views.SubscribeView.as_view()),
    path('billing/verify/', views.CheckoutVerifyView.as_view()),
    path('billing/change-plan/', views.ChangePlanView.as_view()),
    path('billing/cancel/', views.CancelSubscriptionView.as_view()),
    path('billing/payments/', views.PaymentHistoryView.as_view()),

    # --- product owner ----------------------------------------------------
    path('admin/billing/health/', views_admin.AdminBillingHealthView.as_view()),
    path('admin/billing/sync-plans/', views_admin.AdminSyncPlansView.as_view()),
    path('admin/billing/razorpay-plans/', views_admin.AdminRazorpayPlanListView.as_view()),
    path('admin/billing/subscriptions/', views_admin.AdminSubscriptionListView.as_view()),
    path('admin/billing/subscriptions/<int:pk>/reconcile/',
         views_admin.AdminReconcileView.as_view()),
    path('admin/billing/payments/', views_admin.AdminPaymentListView.as_view()),
    path('admin/billing/webhook-events/', views_admin.AdminWebhookEventListView.as_view()),
    path('admin/billing/scheduled-changes/',
         views_admin.AdminScheduledChangeListView.as_view()),
    path('admin/billing/apply-scheduled/',
         views_admin.AdminApplyScheduledChangesView.as_view()),
]
