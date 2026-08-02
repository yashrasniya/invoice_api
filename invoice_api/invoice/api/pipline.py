# views.py
import logging
import os
import uuid
import requests

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.permissions import IsAuthenticated

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser

from accounts.models import ServiceToken, User
from accounts.authenticate import AdminJWTTokenAuthentication
from invoice_api.permissions import HasMethodPermission, HasFeature
from invoice_api.limits import enforce_limit
from invoice.all_serializers.pipline_seriallzers import InvoiceUploadSerializer
from invoice.models import InvoiceExtractionLog


class InvoiceExtractAPIView(APIView):

    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('purchases_invoice')]
    required_permissions_map = {'POST': 'invoice.create'}
    serializer_class = InvoiceUploadSerializer
    @swagger_auto_schema(
        operation_description="Upload invoice file",
        manual_parameters=[
            openapi.Parameter(
                'file',
                openapi.IN_FORM,
                description="Invoice File",
                type=openapi.TYPE_FILE,
                required=True
            ),
            openapi.Parameter(
                'invoice_type',
                openapi.IN_FORM,
                description="Invoice Type (purchase, sales, auto)",
                type=openapi.TYPE_STRING,
                required=False,
                default="purchase"
            )
        ]
    )
    def post(self, request):

        try:
            invoice_type = request.data.get("invoice_type") or request.query_params.get("invoice_type") or "purchase"

            uploaded_file = request.FILES.get("file")

            if not uploaded_file:
                return Response(
                    {"error": "File is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -----------------------------------
            # Plan Limit Check
            # -----------------------------------
            today = timezone.now().date()
            month_count = InvoiceExtractionLog.objects.filter(
                user__user_company=getattr(request, 'company', None),
                created_at__year=today.year,
                created_at__month=today.month
            ).count()
            enforce_limit(request, 'ocr_purchase_invoice', 'ocr_scans_per_month', month_count)

            # -----------------------------------
            # Daily Limit Check
            # -----------------------------------
            today = timezone.now().date()
            daily_count = InvoiceExtractionLog.objects.filter(
                user=request.user,
                created_at__date=today
            ).count()
            
            if daily_count >= 10:
                return Response(
                    {"error": "Daily limit of 10 invoice uploads reached. Please try again tomorrow."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # -----------------------------------
            # Duplicate Filename Check
            # -----------------------------------
            duplicate_exists = InvoiceExtractionLog.objects.filter(
                user=request.user,
                file__endswith=f"_{uploaded_file.name}"
            ).exists()
            
            if duplicate_exists:
                return Response(
                    {"error": f"A document with the name '{uploaded_file.name}' already exists. This is a duplicate."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -----------------------------------
            # Save Uploaded File
            # -----------------------------------

            file_name = f"invoices/{uuid.uuid4()}_{uploaded_file.name}"

            saved_path = default_storage.save(
                file_name,
                uploaded_file
            )

            absolute_file_path = os.path.join(
                settings.MEDIA_ROOT,
                saved_path
            )

            # -----------------------------------
            # Pipeline URL
            # -----------------------------------

            api_base_url = settings.INVOICE_CONVERTOR_PIPLINE_URL

            # -----------------------------------
            # Generate/Get Service Token
            # -----------------------------------


            service_token, created = ServiceToken.objects.get_or_create(
                user=request.user,
                name="invoice-service"
            )

            token = service_token.token

            # -----------------------------------
            # Build User and Company Metadata
            # -----------------------------------
            meta_data = {}
            if request.user:
                meta_data["user"] = {
                    "name": request.user.name() if hasattr(request.user, 'name') else f"{request.user.first_name} {request.user.last_name}",
                    "email": request.user.email,
                    "mobile_number": getattr(request.user, 'mobile_number', '')
                }
                if hasattr(request.user, 'user_company') and request.user.user_company:
                    comp = request.user.user_company
                    meta_data["company"] = {
                        "company_name": comp.company_name,
                        "company_address": comp.company_address,
                        "company_gst_number": comp.company_gst_number,
                        "state": comp.state,
                        "company_email_id": comp.company_email_id
                    }

            # -----------------------------------
            # Call Pipeline API
            # -----------------------------------

            response = requests.post(
                f"{api_base_url}/extract",
                json={
                    "file_path": absolute_file_path,
                    "schema": "",
                    "meta_data": meta_data,
                    "invoice_type": invoice_type
                },
                headers={
                    "Authorization": f"Bearer {token}"
                },
                timeout=300
            )

            # -----------------------------------
            # Parse Response
            # -----------------------------------

            try:
                response_data = response.json()

            except Exception:

                response_data = {
                    "error": "Invalid response from pipeline service",
                    "raw_response": response.text
                }

            # -----------------------------------
            # Store data in DB
            # -----------------------------------
            
            status_value = "success" if response.status_code == 200 else "Extraction Started" if response.status_code==202 else "error"
            
            job_id_value = response_data.get("job_id") if isinstance(response_data, dict) else None
            
            InvoiceExtractionLog.objects.create(
                user=request.user,
                file=saved_path,
                response_data=response_data,
                status=status_value,
                job_id=job_id_value
            )

            return Response(
                response_data,
                status=response.status_code
            )

        except User.DoesNotExist:

            return Response(
                {
                    "error": "Service user not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )

        except Exception as e:

            return Response(
                {
                    "error": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
class InvoiceExtractionStatusAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('purchases_invoice')]
    required_permissions_map = {'GET': 'invoice.view'}

    @swagger_auto_schema(
        operation_description="Check extraction job status",
    )
    def get(self, request, job_id):
        try:
            log_entry = InvoiceExtractionLog.objects.filter(job_id=job_id, user=request.user).first()
            if not log_entry:
                return Response(
                    {"error": "Job not found or access denied"},
                    status=status.HTTP_404_NOT_FOUND
                )

            api_base_url = settings.INVOICE_CONVERTOR_PIPLINE_URL
            service_token, _ = ServiceToken.objects.get_or_create(
                user=request.user,
                name="invoice-service"
            )
            token = service_token.token

            response = requests.get(
                f"{api_base_url}/status/{job_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                log_entry.status = data.get("status", log_entry.status)
                
                if log_entry.response_data and isinstance(log_entry.response_data, dict):
                    log_entry.response_data.update(data)
                else:
                    log_entry.response_data = data
                
                log_entry.save()
                return Response(data, status=status.HTTP_200_OK)
            
            return Response(
                {"error": "Failed to fetch status from pipeline service", "raw_response": response.text},
                status=response.status_code
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class InvoiceExtractionPendingJobsAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('purchases_invoice')]
    required_permissions_map = {'GET': 'invoice.view'}

    @swagger_auto_schema(
        operation_description="Get all pending extraction jobs for the user",
    )
    def get(self, request):
        try:
            pending_logs = InvoiceExtractionLog.objects.filter(
                user=request.user
            ).exclude(
                status__in=["done", "success"]
            ).order_by("-created_at")

            results = []
            for log in pending_logs:
                # Extract filename from the FileField path
                file_name = os.path.basename(log.file.name) if log.file else "Unknown File"
                
                results.append({
                    "job_id": log.job_id,
                    "file_name": file_name,
                    "status": log.status,
                    "created_at": log.created_at
                })

            return Response(results, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

def send_conformation_message(invoice_payload, user):
    message = f"""
    Please review the extracted invoice details below:

    📄 Invoice Number: {invoice_payload.get('invoice_number', 'N/A')}
    📅 Invoice Date: {invoice_payload.get('date', 'N/A')}
    🧾 Invoice Type: {invoice_payload.get('invoice_type', 'N/A')}
    💰 GST Amount: {invoice_payload.get('gst_final_amount', 0)}
    💵 Total Amount: {invoice_payload.get('total_final_amount', 0)}

    Kindly verify that the above information is correct.

    If you notice any incorrect or missing details, you can update them from the dashboard before proceeding.
    """
    
    url = "https://n8n.yashadvertisinggroup.com/webhook/send_whatsapp_message"
    payload = {
        "mobile": user.mobile_number,
        "mobile_number": user.mobile_number,
        "message": message,
        "meta_data": invoice_payload
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        logger = logging.getLogger('invoice')
        logger.info(f"n8n WhatsApp message webhook triggered with status: {response.status_code}")
    except Exception as e:
        logger = logging.getLogger('invoice')
        logger.error(f"Error calling n8n WhatsApp webhook: {str(e)}")


class InvoiceExtractionCallbackAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Update extraction job status via webhook",
    )
    def post(self, request, job_id):
        try:
            log_entry = InvoiceExtractionLog.objects.filter(job_id=job_id, user=request.user).first()
            if not log_entry:
                return Response(
                    {"error": "Job not found or access denied"},
                    status=status.HTTP_404_NOT_FOUND
                )

            status_val = request.data.get("status")
            invoice_type = request.data.get("invoice_type",'')
            if status_val:
                log_entry.status = status_val
                log_entry.invoice_type = invoice_type
                log_entry.meta_data = request.data
                log_entry.save()

                if log_entry.user and log_entry.user.mobile_number:
                    send_conformation_message(request.data, log_entry.user)
            
            return Response({"message": "Status updated successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminInvoiceExtractAPIView(InvoiceExtractAPIView):
    authentication_classes = [AdminJWTTokenAuthentication]

