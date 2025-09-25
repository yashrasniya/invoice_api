import os
import json
from django.utils import timezone
from datetime import timedelta

import requests
from dotenv import load_dotenv
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from bill_share.caption import caption
from bill_share.models import BillShare
from bill_share.serializers import BillShareSerializers
from invoice.export import pdf_generator
from invoice.models import Invoice

# Load environment variables
load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")

def upload_pdf(file_io_obj):
    """
    Upload local PDF to WhatsApp Cloud API and return media_id
    """
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    files = {
        "file": ("invoice.pdf", file_io_obj, "application/pdf")
    }
    data = {
        "messaging_product": "whatsapp",
        "type": "application/pdf"
    }

    response = requests.post(url, headers=headers, files=files, data=data)

    if response.status_code == 200:
        media_id = response.json().get("id")
        print(f"✅ Uploaded PDF. Media ID: {media_id}")
        return media_id
    else:
        print("❌ Upload failed:", response.json())
        return None



def send_pdf(media_id,phone_number, caption="📄 Here is your PDF file."):
    """
    Send uploaded PDF to recipient using WhatsApp Cloud API
    """
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "document",
        "document": {
            "id": media_id,
            "caption": caption
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print(response.json())
    return response.status_code == 200

def send_message_by_template(RECIPIENT_PHONE,receiver,company_name,total_final_amount,MEDIA_ID):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Template message body
    data = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE,
        "type": "template",
        "template": {
            "name": "here_is_your_bill_with_time",
            "language": {"code": "en_US"},  # must match template language
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "document",
                            "document": {
                                "id": MEDIA_ID,  # 👈 use the media ID
                                "filename": "Invoice.pdf"
                            }
                        }
                    ]
                },
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(receiver)},  # {{1}}
                        {"type": "text", "text": str(company_name)},  # {{2}}
                        {"type": "text", "text": str(total_final_amount)}  # {{3}}
                    ]
                }
            ]
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))

    print("Status Code:", response.status_code)
    print("Response:", response.json())
    return response.status_code == 200

def list_of_message_templates():
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_BUSINESS_ACCOUNT_ID}/message_templates"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    params = {
        "limit": 50  # you can paginate if you have more than 50
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        templates = response.json()
        print(templates)
        for t in templates.get("data", []):
            print(f"Name: {t['name']}, Language: {t['language']}, Status: {t['status']}")
    else:
        print("Error:", response.status_code, response.text)

class ShareByWhatsapp(APIView):
    permission_classes = [IsAuthenticated]

    def get_count(self):
        now = timezone.now()

        # 24 hours ago
        last_24h = now - timedelta(hours=24)

        # Count BillShare objects created in the last 24 hours
        count_last_24h = BillShare.objects.filter(created_at__gte=last_24h,user=self.request.user).count()
        return count_last_24h
    def post(self, request):
        data = request.data.copy()
        data["user"] = request.user.id  # ✅ inject the logged-in user
        template_id = data.get("template_id")
        qs = Invoice.objects.filter(id=data.get("invoice"), user=request.user)
        if not (qs.first() and qs.first().receiver.phone_number):
            return Response({"error": f"Phone number is not set for {qs.first().receiver.name}"}, 400)
        phone_number = qs.first().receiver.phone_number
        if phone_number.startswith("+"):
            phone_number = phone_number[1:]

        # Reject if contains non-numeric characters
        if not phone_number.isdigit():
            return Response({"error": "Phone number must contain only digits"}, 400)

        if len(phone_number)==11 and phone_number.startswith('0'):
            phone_number = phone_number[1:]
        # If 10 digits, prefix with '91'
        if len(phone_number) == 10:
            phone_number = "91" + phone_number

        print(phone_number)
        # Reject if not exactly 12 digits
        if len(phone_number) != 12:
            return Response({"error": "Phone number must be exactly 12 digits (with country code)"}, 400)
        data["to"] = phone_number
        list_of_message_templates()
        if self.get_count() > 20:
            return Response({"error": "You have reached the maximum limit of shares/messages for today. Please try again tomorrow."}, 400)
        ser = BillShareSerializers(data=data)
        if ser.is_valid():
            obj = ser.save()
            io_obj = pdf_generator(qs, request, return_bytes=True,template_id=template_id)
            if not io_obj:
                return Response({
                                    "error": "Some thing went wrong connect to admin"},
                                400)

            media_id = upload_pdf(io_obj)
            company_name= obj.user.name
            if obj.user.user_company:
                company_name = obj.invoice.user.user_company.company_name
            error_message = "File not uploaded"
            if media_id:
                # if send_pdf(media_id,caption=caption.format(obj.invoice.receiver.name,company_name,obj.invoice.total_final_amount), phone_number=phone_number):
                if send_message_by_template(phone_number,obj.invoice.receiver.name,company_name,obj.invoice.total_final_amount,media_id):
                    return Response({}, 201)
                error_message = "Message not able to send"
            return Response({"error": error_message})
        else:
            return Response(ser.errors, 400)




