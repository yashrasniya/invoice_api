from django.urls import path
from .views import InvoiceView, Invoice_update, Invoice_product_action, new_product_in_frontend_view, \
    new_product_in_frontend_update_view, ProductViewSet, ProductPropertiesViewsSet, PDF_maker

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
    path('pdf/',PDF_maker.as_view())

]