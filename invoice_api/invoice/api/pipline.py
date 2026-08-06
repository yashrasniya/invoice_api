# views.py
import logging
import os
import uuid
import requests

from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import Q
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
from invoice_api.limits import enforce_limit, get_limit
from invoice_api.scoping import user_scope_q
from invoice.all_serializers.pipline_seriallzers import InvoiceUploadSerializer
from invoice.models import InvoiceExtractionLog

# Per-user cap on uploads per calendar day, on top of the plan's monthly quota.
DAILY_UPLOAD_LIMIT = 10

# Pipeline statuses that mean the job finished successfully / failed. Anything
# else ("Extraction Started", "queued", …) is still in flight.
DONE_STATUSES = ("done", "success")
FAILED_STATUSES = ("error", "failed")


def status_match_q(values):
    """Case-insensitive `status IN values`, so counting happens in the DB."""
    q = Q()
    for value in values:
        q |= Q(status__iexact=value)
    return q


def extraction_state(status_value):
    """Collapse the pipeline's free-form status into completed/processing/failed."""
    value = (status_value or "").strip().lower()
    if value in DONE_STATUSES:
        return "completed"
    if value in FAILED_STATUSES:
        return "failed"
    return "processing"


def extracted_summary(log):
    """Pull the headline invoice fields out of a log's stored payloads.

    The callback writes the pipeline's final payload to `meta_data`, while
    `response_data` holds the initial /extract reply (and any status polls),
    so prefer meta_data and fall back to response_data.
    """
    top_level = [s for s in (log.meta_data, log.response_data) if isinstance(s, dict)]
    # some pipeline versions nest the invoice under `data`/`invoice`/`result`
    nested = [s[key] for s in top_level
              for key in ("data", "invoice", "result")
              if isinstance(s.get(key), dict)]
    sources = top_level + nested

    def pick(*keys):
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value not in (None, "", []):
                    return value
        return None

    # `vendor` may hold either a name or a Vendor pk depending on which stage
    # of the pipeline wrote it — keep them apart so an id never renders as a name
    vendor = pick("vendor_name", "vendor", "party_name", "seller_name")
    vendor_name, vendor_id = vendor, None
    if isinstance(vendor, bool):
        vendor_name = None
    elif isinstance(vendor, int):
        vendor_name, vendor_id = None, vendor
    elif isinstance(vendor, str) and vendor.strip().isdigit():
        vendor_name, vendor_id = None, int(vendor.strip())

    return {
        "invoice_number": pick("invoice_number", "invoiceNumber", "bill_number"),
        "date": pick("date", "invoice_date"),
        "vendor_name": vendor_name,
        "vendor_id": vendor_id,
        "total_amount": pick("total_final_amount", "total_amount", "grand_total"),
        "gst_amount": pick("gst_final_amount", "gst_amount", "tax_amount"),
    }


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
            # localdate(), not now().date(): the latter yields the UTC date,
            # while the __date/__month lookups convert to TIME_ZONE — so they
            # disagree for the first 5.5h of every IST day.
            today = timezone.localdate()
            month_count = InvoiceExtractionLog.objects.filter(
                user__user_company=getattr(request, 'company', None),
                created_at__year=today.year,
                created_at__month=today.month
            ).count()
            enforce_limit(request, 'ocr_purchase_invoice', 'ocr_scans_per_month', month_count)

            # -----------------------------------
            # Daily Limit Check
            # -----------------------------------
            daily_count = InvoiceExtractionLog.objects.filter(
                user=request.user,
                created_at__date=today
            ).count()
            
            if daily_count >= DAILY_UPLOAD_LIMIT:
                return Response(
                    {"error": f"Daily limit of {DAILY_UPLOAD_LIMIT} invoice uploads reached. Please try again tomorrow."},
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

class InvoiceExtractionJobsAPIView(APIView):
    """Full OCR extraction history + quota usage, for the OCR Invoices page.

    `purchase/pending-jobs/` deliberately returns only unfinished jobs (it
    backs a notification dropdown). This one returns everything, company-wide,
    with the extracted fields so the page can show what OCR actually read.
    """
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('purchases_invoice')]
    required_permissions_map = {'GET': 'invoice.view'}

    MAX_PAGE = 200

    @swagger_auto_schema(
        operation_description="List OCR extraction jobs with extracted data and plan usage",
    )
    def get(self, request):
        try:
            logs = (InvoiceExtractionLog.objects
                    .filter(user_scope_q(request))
                    .order_by('-created_at'))

            try:
                limit = int(request.query_params.get('limit') or 50)
            except (TypeError, ValueError):
                limit = 50
            limit = max(1, min(limit, self.MAX_PAGE))

            state_filter = (request.query_params.get('state') or '').strip().lower()

            # localdate() to match the __date/__month lookups below, which
            # convert to TIME_ZONE; now().date() would give the UTC date and
            # report 0 uploads during the first 5.5h of every IST day.
            today = timezone.localdate()
            # counts/usage are aggregated in the DB over the whole history, so
            # they stay correct no matter which page or filter is requested
            this_month = logs.filter(created_at__year=today.year,
                                     created_at__month=today.month).count()
            today_count = InvoiceExtractionLog.objects.filter(
                user=request.user, created_at__date=today).count()

            done_q = status_match_q(DONE_STATUSES)
            failed_q = status_match_q(FAILED_STATUSES)
            total = logs.count()
            completed_count = logs.filter(done_q).count()
            failed_count = logs.filter(failed_q).count()
            counts = {
                "completed": completed_count,
                "failed": failed_count,
                # everything not terminal is still in flight (incl. null status)
                "processing": total - completed_count - failed_count,
            }

            page = logs
            if state_filter == 'completed':
                page = logs.filter(done_q)
            elif state_filter == 'failed':
                page = logs.filter(failed_q)
            elif state_filter == 'processing':
                page = logs.exclude(done_q).exclude(failed_q)

            jobs = []
            for log in page.select_related('user')[:limit]:
                state = extraction_state(log.status)

                file_name, file_url = "Unknown File", None
                if log.file:
                    file_name = os.path.basename(log.file.name)
                    try:
                        file_url = request.build_absolute_uri(log.file.url)
                    except ValueError:
                        file_url = None

                jobs.append({
                    "id": log.id,
                    "job_id": log.job_id,
                    "file_name": file_name,
                    "file_url": file_url,
                    "status": log.status,
                    "state": state,
                    "invoice_type": log.invoice_type,
                    "created_at": log.created_at,
                    "uploaded_by": log.user.username if log.user else None,
                    "extracted": extracted_summary(log),
                })

            # resolve any vendor pks the pipeline stored into display names,
            # in one query rather than one per job
            vendor_ids = {j["extracted"]["vendor_id"] for j in jobs
                          if j["extracted"].get("vendor_id")}
            if vendor_ids:
                from companies.models import Vendor
                names = dict(Vendor.objects
                             .filter(user_scope_q(request), id__in=vendor_ids)
                             .values_list('id', 'name'))
                for job in jobs:
                    ex = job["extracted"]
                    if ex.get("vendor_id") and not ex.get("vendor_name"):
                        ex["vendor_name"] = names.get(ex["vendor_id"])

            return Response({
                "usage": {
                    "this_month": this_month,
                    # None => unlimited, 0 => no active plan
                    "monthly_limit": get_limit(request, 'ocr_purchase_invoice', 'ocr_scans_per_month'),
                    "today": today_count,
                    "daily_limit": DAILY_UPLOAD_LIMIT,
                    "total": total,
                },
                "counts": counts,
                "jobs": jobs,
            }, status=status.HTTP_200_OK)

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

