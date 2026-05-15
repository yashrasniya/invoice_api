# views.py

import os
import uuid
import requests

from django.conf import settings
from django.core.files.storage import default_storage
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.permissions import IsAuthenticated

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser

from accounts.models import ServiceToken, User
from invoice.all_serializers.pipline_seriallzers import InvoiceUploadSerializer


class InvoiceExtractAPIView(APIView):

    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]
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
            )
        ]
    )
    def post(self, request):

        try:

            uploaded_file = request.FILES.get("file")

            if not uploaded_file:
                return Response(
                    {"error": "File is required"},
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
            # Call Pipeline API
            # -----------------------------------

            response = requests.post(
                f"{api_base_url}/extract",
                json={
                    "file_path": absolute_file_path,
                    "schema": ""
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