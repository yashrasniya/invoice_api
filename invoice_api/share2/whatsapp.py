import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
RECIPIENT_PHONE = os.getenv("RECIPIENT_PHONE")

def upload_pdf(file_path):
    """
    Upload local PDF to WhatsApp Cloud API and return media_id
    """
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    files = {
        "file": ("invoice.pdf", open(file_path, "rb"), "application/pdf")
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



def send_pdf(media_id, caption="📄 Here is your PDF file."):
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
        "to": RECIPIENT_PHONE,
        "type": "document",
        "document": {
            "id": media_id,
            "caption": caption
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))

    if response.status_code == 200:
        print("✅ PDF sent successfully:", response.json())
    else:
        print("❌ Failed to send PDF:", response.json())


if __name__ == "__main__":
    pdf_path = "invoice.pdf"  # Change this to your local PDF file
    media_id = upload_pdf(pdf_path)

    if media_id:
        send_pdf(media_id)
