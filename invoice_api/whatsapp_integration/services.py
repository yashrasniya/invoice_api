import requests
import json
import logging

logger = logging.getLogger('invoice')

def register_whatsapp_number(access_token, phone_number_id, pin):
    """
    Register a phone number with Meta WhatsApp Business API.
    """
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/register"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "pin": pin
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error registering WhatsApp number: {e}")
        if e.response is not None:
             logger.error(f"Response: {e.response.text}")
        return {"error": str(e), "details": e.response.text if e.response else "No response"}

def validate_access_token(access_token):
    """
    Validate Meta access token.
    """
    url = "https://graph.facebook.com/v20.0/me"
    params = {
        "access_token": access_token
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error validating access token: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {
            "error": str(e),
            "details": e.response.text if e.response else "No response"
        }

def validate_waba_id(access_token, business_account_id):
    """
    Validate WhatsApp Business Account (WABA_ID).
    """
    url = f"https://graph.facebook.com/v20.0/{business_account_id}"
    params = {
        "access_token": access_token
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error validating WABA ID: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {
            "error": str(e),
            "details": e.response.text if e.response else "No response"
        }

def validate_phone_number_id(access_token, phone_number_id):
    """
    Validate WhatsApp Phone Number ID.
    """
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}"
    params = {
        "access_token": access_token
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error validating phone number ID: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {
            "error": str(e),
            "details": e.response.text if e.response else "No response"
        }

def send_test_message(access_token, phone_number_id, to_number):
    """
    Send test WhatsApp message to verify full setup.
    """
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": "hello_world",
            "language": {
                "code": "en_US"
            }
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending test message: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {
            "error": str(e),
            "details": e.response.text if e.response else "No response"
        }

def validate_whatsapp_integration(access_token, business_account_id, phone_number_id):
    """
    Full validation pipeline.
    """
    results = {}

    results["token"] = validate_access_token(access_token)
    if "error" in results["token"]:
        return "error","access_token"

    results["waba"] = validate_waba_id(access_token, business_account_id)
    if "error" in results["waba"]:
        return "error","waba_id"

    results["phone"] = validate_phone_number_id(access_token, phone_number_id)
    if "error" in results["phone"]:
        return "error","phone_number_id"

    results["status"] = "valid"
    return "valid",results

def create_whatsapp_template(
    access_token,
    business_account_id,
    template_name,
    category,
    language="en_US",
    components=None
):
    """
    Create a WhatsApp message template using latest Cloud API.
    """

    url = f"https://graph.facebook.com/v20.0/{business_account_id}/message_templates"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "name": template_name.lower().replace(" ", "_"),  # required format
        "category": category.upper(),  # UTILITY / MARKETING / AUTHENTICATION
        "language": language,
        "components": components or [
            {
                "type": "BODY",
                "text": "Hello {{1}}, this is a sample message."
            }
        ]
    }
    print(payload)
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"Error creating WhatsApp template: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {
            "error": str(e),
            "details": e.response.text if e.response else "No response"
        }


def send_whatsapp_message(access_token, phone_number_id, recipient_number, template_name, language_code="en_US"):
    """
    Send a WhatsApp template message.
    """
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code
            }
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending WhatsApp message: {e}")
        if e.response is not None:
             logger.error(f"Response: {e.response.text}")
        return {"error": str(e), "details": e.response.text if e.response else "No response"}

def update_whatsapp_template(access_token, template_id, components):
    """
    Update an existing WhatsApp template on Meta by its template ID.
    Note: You can only edit templates if they are Rejected, Paused, or Approved (sometimes).
    """
    url = f"https://graph.facebook.com/v19.0/{template_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "components": components
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error updating WhatsApp template: {e}")
        if e.response is not None:
             logger.error(f"Response: {e.response.text}")
        return {"error": str(e), "details": e.response.text if e.response else "No response"}

def fetch_whatsapp_templates(access_token, business_account_id):
    """
    Fetch all templates from Meta to support syncing.
    """
    url = f"https://graph.facebook.com/v19.0/{business_account_id}/message_templates"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching WhatsApp templates: {e}")
        if e.response is not None:
             logger.error(f"Response: {e.response.text}")
        return {"error": str(e), "details": e.response.text if e.response else "No response"}

def exchange_meta_code_for_token(code):
    """
    Exchange Meta OAuth code for a WhatsApp access token.
    Requires META_APP_SECRETs safely placed in environment.
    """
    import os
    app_id = "434279422908745" # Extracted from HTML
    app_secret = os.environ.get("META_APP_SECRET")
    
    if not app_secret:
         return {"error": "META_APP_SECRET environment variable is missing"}

    url = "https://graph.facebook.com/v20.0/oauth/access_token"
    params = {
        "client_id": app_id,
        "client_secret": app_secret,
        "code": code
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Access Token Exchange: {e}")
        if e.response is not None:
             logger.error(f"Response: {e.response.text}")
        return {"error": str(e), "details": e.response.text if e.response else "No response"}


def upload_pdf(file_io_obj,business_id,access_token):
    """
    Upload local PDF to WhatsApp Cloud API and return media_id
    """


    url = f"https://graph.facebook.com/v20.0/{business_id}/uploads"

    params = {
        "file_name": "bill.pdf",
        "file_length": 12345,  # size in bytes
        "file_type": "application/pdf",
        "access_token": access_token
    }


    response = requests.post(url, params=params, data=file_io_obj)
    if response.status_code == 200:

        return upload_file_to_meta(access_token,response.json()["id"])

    else:
        return None

def upload_file_to_meta(access_token, upload_id, file_path="invoice_api/template.pdf"):
    """
    Upload file to Meta upload session (STEP 2)
    """

    url = f"https://graph.facebook.com/v20.0/{upload_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "file_offset": "0",
        "Content-Type": "application/octet-stream"
    }

    try:
        with open(file_path, "rb") as f:
            response = requests.post(url, headers=headers, data=f)

        response.raise_for_status()

        result = response.json()
        print("✅ Upload Success:", result)

        return result["h"]

    except requests.exceptions.RequestException as e:
        logger.error(f"Error uploading file: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {
            "error": str(e),
            "details": e.response.text if e.response else "No response"
        }

def create_bill_template(access_token, business_account_id,phone_number_id, name = 'here_is_your_bill_with_time'):
    """
    Create WhatsApp template: here_is_your_bill_with_time
    """
    BASE_URL = "https://graph.facebook.com/v19.0"

    url = f"{BASE_URL}/{business_account_id}/message_templates"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    with open("invoice_api/template.pdf", 'rb') as fh:

        media_id = upload_pdf(fh,phone_number_id,access_token)
    payload = {
        "name": f"{name}",
        "language": "en_US",
        "category": "UTILITY",
        "parameter_format": "POSITIONAL",
        "components": [
            {
                "type": "HEADER",
                "format": "DOCUMENT",
                "example": {
                    "header_handle": [
                        f"{media_id}"
                    ]
                }
            },
            {
                "type": "BODY",
                "text": "Hello {{1}},\n\nHere is your bill from {{2}}.\nAmount: ₹ {{3}}\n\nThe detailed bill is attached as a PDF.\n\nThank you for your business!",
                "example": {
                    "body_text": [
                        [
                            "Rakesh",
                            "Yash Advertising Group",
                            "5432"
                        ]
                    ]
                }
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        logger.info("✅ Template created successfully")
        response.json()
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error creating template: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
        print({
            "error": str(e),
            "details": e.response.text if e.response else "No response"
        })
        return False


