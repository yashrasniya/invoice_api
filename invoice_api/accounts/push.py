"""Send push notifications to a user's registered phones through Expo's push service.

Best-effort by design: a failed push must never fail the request that triggered it
(an OCR callback, an invoice save), so everything here swallows and logs errors.
"""
import logging

import requests

from accounts.models import DeviceToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'
EXPO_TOKEN_PREFIXES = ('ExponentPushToken[', 'ExpoPushToken[')
MAX_BATCH = 100   # Expo accepts at most 100 messages per request


def is_expo_token(token):
    return isinstance(token, str) and token.startswith(EXPO_TOKEN_PREFIXES) and token.endswith(']')


def send_push(user, title, body, data=None):
    """Notify every device `user` has registered. Returns the number accepted by Expo."""
    tokens = list(DeviceToken.objects.filter(user=user).values_list('token', flat=True))
    if not tokens:
        return 0

    accepted = 0
    for i in range(0, len(tokens), MAX_BATCH):
        batch = tokens[i:i + MAX_BATCH]
        messages = [{'to': t, 'title': title, 'body': body, 'data': data or {}, 'sound': 'default'}
                    for t in batch]
        try:
            res = requests.post(EXPO_PUSH_URL, json=messages, timeout=10,
                                headers={'Accept': 'application/json'})
            results = res.json().get('data', [])
        except Exception:
            logger.exception('push send failed for user %s', user.pk)
            continue

        for token, result in zip(batch, results):
            if result.get('status') == 'ok':
                accepted += 1
            elif (result.get('details') or {}).get('error') == 'DeviceNotRegistered':
                # the app was uninstalled or the token rotated: stop sending to it
                DeviceToken.objects.filter(token=token).delete()
    return accepted
