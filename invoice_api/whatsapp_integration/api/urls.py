from django.urls import path
from .views import WhatsAppConfigAPIView, WhatsAppTemplateAPIView, WhatsAppSendTestAPIView, WhatsAppTemplateDetailAPIView, WhatsAppTemplateSyncAPIView, WhatsAppOAuthAPIView

urlpatterns = [
    path('whatsapp/config/', WhatsAppConfigAPIView.as_view(), name='whatsapp_config'),
    path('whatsapp/template/', WhatsAppTemplateAPIView.as_view(), name='whatsapp_template'),
    path('whatsapp/template/sync/', WhatsAppTemplateSyncAPIView.as_view(), name='whatsapp_template_sync'),
    path('whatsapp/template/<int:pk>/', WhatsAppTemplateDetailAPIView.as_view(), name='whatsapp_template_detail'),
    path('whatsapp/send-test/', WhatsAppSendTestAPIView.as_view(), name='whatsapp_send_test'),
    path('whatsapp/oauth/', WhatsAppOAuthAPIView.as_view(), name='whatsapp_oauth'),
]
