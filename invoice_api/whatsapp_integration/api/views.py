from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from ..models import WhatsAppIntegration, WhatsAppTemplate, WhatsAppMessage
from ..services import register_whatsapp_number, create_whatsapp_template, send_whatsapp_message, \
    validate_whatsapp_integration, update_whatsapp_template, fetch_whatsapp_templates, exchange_meta_code_for_token, create_bill_template


class WhatsAppConfigAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            integration = WhatsAppIntegration.objects.get(user=request.user)
            return Response({
                "status": integration.status,
                "business_account_id": integration.business_account_id,
                "phone_number_id": integration.phone_number_id,
                "created_at": integration.created_at
            })
        except WhatsAppIntegration.DoesNotExist:
            return Response({"status": "not_configured"}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        data = request.data
        access_token = data.get("access_token")
        phone_number_id = data.get("phone_number_id")
        business_account_id = data.get("business_account_id")
        pin = data.get("pin") # required for registration

        if not all([access_token, phone_number_id, business_account_id, pin]):
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        # Update or create the config
        integration, created = WhatsAppIntegration.objects.update_or_create(
            user=request.user,
            defaults={
                "access_token": access_token,
                "phone_number_id": phone_number_id,
                "business_account_id": business_account_id,
                "status": "pending"
            }
        )

        # Trigger registration
        reg_response,not_valid_key = validate_whatsapp_integration(access_token, business_account_id, phone_number_id)

        if "error" in reg_response:
            integration.status = "failed"
            integration.save()
            return Response({"error": f"Failed to register {not_valid_key}", "details": reg_response}, status=status.HTTP_400_BAD_REQUEST)
        template_name = "here_is_your_bill_with_time"
        response = create_bill_template(access_token, business_account_id, pin, template_name)
        if not response:
            return Response({"error": f"Failed to create new template", "details": reg_response}, status=status.HTTP_400_BAD_REQUEST)
        integration.status = "active"
        integration.default_template_name = template_name
        integration.save()

        print(response)

        return Response({"message": "WhatsApp number registered successfully", "status": "active"}, status=status.HTTP_200_OK)


class WhatsAppTemplateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        templates = WhatsAppTemplate.objects.filter(user=request.user).values(
            'id', 'template_name', 'category', 'status', 'meta_template_id', 'created_at'
        )
        return Response(templates)

    def post(self, request):
        user = request.user
        try:
            integration = WhatsAppIntegration.objects.get(user=user, status="active")
        except WhatsAppIntegration.DoesNotExist:
            return Response({"error": "Active WhatsApp integration not found"}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data
        template_name = data.get("template_name")
        category = data.get("category", "UTILITY").upper()
        language = data.get("language", "en_US")
        components = data.get("components", [])

        if not template_name or not components:
             return Response({"error": "template_name and components are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Trigger Meta Template Creation
        meta_response = create_whatsapp_template(
            integration.access_token, 
            integration.business_account_id, 
            template_name, 
            category, 
            language, 
            components
        )

        if "error" in meta_response:
            return Response({"error": "Failed to create template on Meta", "details": meta_response}, status=status.HTTP_400_BAD_REQUEST)

        template_id = meta_response.get("id", "")

        # Save to DB
        template = WhatsAppTemplate.objects.create(
            user=user,
            template_name=template_name,
            template_body=str(components), # Simplified storage for body
            category=category.lower(),
            status="pending",
            meta_template_id=template_id
        )

        return Response({"message": "Template submitted for approval", "template_id": template.id, "meta_template_id": template_id}, status=status.HTTP_201_CREATED)


class WhatsAppSendTestAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        try:
            integration = WhatsAppIntegration.objects.get(user=user, status="active")
        except WhatsAppIntegration.DoesNotExist:
            return Response({"error": "Active WhatsApp integration not found"}, status=status.HTTP_400_BAD_REQUEST)

        recipient_number = request.data.get("recipient_number")
        template_name = request.data.get("template_name")

        if not recipient_number or not template_name:
            return Response({"error": "recipient_number and template_name are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Log Queued
        msg_log = WhatsAppMessage.objects.create(
            user=user,
            phone_number_id=integration.phone_number_id,
            recipient_number=recipient_number,
            template_id=template_name,
            status="queued"
        )

        # Send
        send_resp = send_whatsapp_message(
            integration.access_token,
            integration.phone_number_id,
            recipient_number,
            template_name
        )

        if "error" in send_resp:
            msg_log.status = "failed"
            msg_log.save()
            return Response({"error": "Failed to send message", "details": send_resp}, status=status.HTTP_400_BAD_REQUEST)

        msg_log.status = "sent"
        
        # Meta returns messages array
        messages_info = send_resp.get("messages", [])
        if messages_info:
            msg_log.meta_message_id = messages_info[0].get("id")
        msg_log.save()

        return Response({"message": "Test message sent successfully"}, status=status.HTTP_200_OK)


class WhatsAppTemplateDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        user = request.user
        try:
            integration = WhatsAppIntegration.objects.get(user=user, status="active")
        except WhatsAppIntegration.DoesNotExist:
            return Response({"error": "Active WhatsApp integration not found"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            template = WhatsAppTemplate.objects.get(pk=pk, user=user)
        except WhatsAppTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        components = data.get("components", [])

        if not components:
            return Response({"error": "components are required to update"}, status=status.HTTP_400_BAD_REQUEST)

        # Update on Meta
        if template.meta_template_id:
            meta_response = update_whatsapp_template(
                integration.access_token,
                template.meta_template_id,
                components
            )

            if "error" in meta_response:
                return Response({"error": "Failed to update template on Meta", "details": meta_response}, status=status.HTTP_400_BAD_REQUEST)

        # Update DB
        template.template_body = str(components)
        if data.get("template_name"):
             template.template_name = data.get("template_name")
        template.status = "pending" # Reset to pending when edited if required, or keep current depending on Meta response
        template.save()

        return Response({"message": "Template updated successfully"}, status=status.HTTP_200_OK)


class WhatsAppTemplateSyncAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        try:
            integration = WhatsAppIntegration.objects.get(user=user, status="active")
        except WhatsAppIntegration.DoesNotExist:
            return Response({"error": "Active WhatsApp integration not found"}, status=status.HTTP_400_BAD_REQUEST)

        meta_data = fetch_whatsapp_templates(integration.access_token, integration.business_account_id)

        if "error" in meta_data:
            return Response({"error": "Failed to fetch templates from Meta", "details": meta_data}, status=status.HTTP_400_BAD_REQUEST)

        synced_count = 0
        added_count = 0
        templates_from_meta = meta_data.get("data", [])

        for meta_tpl in templates_from_meta:
            meta_id = meta_tpl.get("id")
            name = meta_tpl.get("name")
            category = meta_tpl.get("category", "utility").lower()
            meta_status = meta_tpl.get("status", "pending").lower()
            components = meta_tpl.get("components", [])
            
            # Map statuses
            # Meta statuses are like APPROVED, REJECTED, PENDING, PAUSED.
            mapped_status = meta_status
            if mapped_status in ['pending_deletion', 'deleted']:
                continue # optionally handle deletions

            tpl_obj, created = WhatsAppTemplate.objects.update_or_create(
                user=user,
                meta_template_id=meta_id,
                defaults={
                    "template_name": name,
                    "category": category,
                    "status": mapped_status,
                    "template_body": str(components)
                }
            )

            if created:
                added_count += 1
            else:
                synced_count += 1

        return Response({
            "message": "Templates synced successfully",
            "added": added_count,
            "updated": synced_count
        }, status=status.HTTP_200_OK)


class WhatsAppOAuthAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        code = request.data.get("code")
        waba_id = request.data.get("waba_id")
        phone_number_id = request.data.get("phone_number_id")

        if not code or not waba_id or not phone_number_id:
            return Response({"error": "Missing code, waba_id, or phone_number_id"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Exchange the code for an access token
        exchange_result = exchange_meta_code_for_token(code)
        if "error" in exchange_result:
            return Response({"error": "Failed to exchange OAuth token", "details": exchange_result}, status=status.HTTP_400_BAD_REQUEST)

        access_token = exchange_result.get("access_token")

        if not access_token:
             return Response({"error": "No access token found in response", "details": exchange_result}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Update config locally
        integration, _ = WhatsAppIntegration.objects.update_or_create(
            user=user,
            defaults={
                "access_token": access_token,
                "phone_number_id": phone_number_id,
                "business_account_id": waba_id,
                "status": "pending"
            }
        )

        # 3. Quick ping test to validate
        reg_response, not_valid_key = validate_whatsapp_integration(access_token, waba_id, phone_number_id)

        if "error" in reg_response:
            integration.status = "failed"
            integration.save()
            return Response({"error": f"Failed to register {not_valid_key}", "details": reg_response}, status=status.HTTP_400_BAD_REQUEST)

        integration.status = "active"
        integration.save()

        return Response({"message": "WhatsApp Embedded Signup integrated successfully", "status": "active"}, status=status.HTTP_200_OK)
