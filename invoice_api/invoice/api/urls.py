from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .pipline import InvoiceExtractAPIView, InvoiceExtractionStatusAPIView, InvoiceExtractionPendingJobsAPIView, InvoiceExtractionCallbackAPIView, AdminInvoiceExtractAPIView, InvoiceExtractionJobsAPIView
from .views import InvoiceView, Invoice_update, Invoice_product_action, new_product_in_frontend_view, \
    new_product_in_frontend_update_view, ProductViewSet, ProductPropertiesViewsSet, PdfMaker, BulkExport, \
    CustomFieldViewSet, LedgerAPIView

router = DefaultRouter()
router.register(r'custom-fields', CustomFieldViewSet, basename='custom-field')

from .report_views import CashFlowReportAPIView, PurchaseInvoiceSummaryAPIView, GSTSummaryAPIView
from .sales_report_views import SalesReportAPIView

urlpatterns = [
    path('invoice/', InvoiceView.as_view()),
    path('invoice/<int:id>/', InvoiceView.as_view()),
    path('invoice/<int:id>/update/', Invoice_update.as_view()),
    path('invoice/<int:id>/product/<str:action>/', Invoice_product_action.as_view()),
    # new_product_in_frontend_view
    path('new/product/in/frontend/', new_product_in_frontend_view.as_view()),
    path('new/product/in/frontend/<int:id>/', new_product_in_frontend_view.as_view()),
    path('new/product/in/frontend/<int:id>/update/', new_product_in_frontend_update_view.as_view()),
    # ProductViewSet
    path('product/', ProductViewSet.as_view()),
    path('product/<int:id>/update/', ProductViewSet.as_view()),
    # InvoiceViewSet
    path('product/properties/',ProductPropertiesViewsSet.as_view()),
    path('product/properties/<int:id>/update/',ProductPropertiesViewsSet.as_view()),
    # pdf
    path('pdf/', PdfMaker.as_view()),
    path('bulk_export/', BulkExport.as_view()),
    path('sales-report/', SalesReportAPIView.as_view()),
    path('cash-flow/', CashFlowReportAPIView.as_view()),
    path('gst-summary/', GSTSummaryAPIView.as_view()),
    path('ledger/<str:entity_type>/<int:entity_id>/', LedgerAPIView.as_view()),
    path('purchase-summary/', PurchaseInvoiceSummaryAPIView.as_view()),
    path('purchase/upload/', InvoiceExtractAPIView.as_view()),
    path('purchase/upload-admin/', AdminInvoiceExtractAPIView.as_view()),
    path('purchase/status/<str:job_id>/', InvoiceExtractionStatusAPIView.as_view()),
    path('purchase/pending-jobs/', InvoiceExtractionPendingJobsAPIView.as_view()),
    path('purchase/ocr-jobs/', InvoiceExtractionJobsAPIView.as_view()),
    path('purchase/callback/<str:job_id>/', InvoiceExtractionCallbackAPIView.as_view(), name='purchase-callback')
] + router.urls