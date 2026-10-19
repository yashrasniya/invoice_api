"""Verify a Firebase phone-auth ID token and return the phone number Firebase vouches for."""
import logging

from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from accounts.mobile import normalize_mobile

logger = logging.getLogger(__name__)


class PhoneTokenError(Exception):
    def __init__(self, message, status=401):
        super().__init__(message)
        self.message, self.status = message, status


def verify_phone_id_token(id_token):
    """(firebase_uid, normalised_mobile) or raise PhoneTokenError."""
    if not settings.FIREBASE_PROJECT_ID:
        logger.error("Phone verification: FIREBASE_PROJECT_ID is not configured")
        raise PhoneTokenError('Phone login is not available.', 503)

    # signature (Firebase public certs), exp, aud == project id
    project = settings.FIREBASE_PROJECT_ID
    try:
        claims = google_id_token.verify_firebase_token(
            id_token, google_requests.Request(), audience=project, clock_skew_in_seconds=10)
    except ValueError:
        claims = None
    if (not claims
            or claims.get('iss') != f'https://securetoken.google.com/{project}'
            or (claims.get('firebase') or {}).get('sign_in_provider') != 'phone'):
        logger.warning("Phone verification: invalid Firebase ID token")
        raise PhoneTokenError('Invalid or expired token.')

    uid = claims.get('user_id') or claims.get('sub')
    mobile = normalize_mobile(claims.get('phone_number'))
    if not uid or not mobile:
        raise PhoneTokenError('Token has no verified phone number.')
    return uid, mobile
