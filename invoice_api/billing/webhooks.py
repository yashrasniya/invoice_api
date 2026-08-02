"""Razorpay webhook receiver.

Security properties this endpoint guarantees:

* The HMAC-SHA256 signature is verified against the **raw** request body before
  anything is parsed or persisted. An unsigned or mis-signed request is a 400
  and touches no state.
* Every event is recorded under Razorpay's own `X-Razorpay-Event-Id` with a
  unique constraint, so a replayed delivery is a no-op. Razorpay retries
  aggressively; without this, `subscription.charged` would extend a period
  twice.
* Nothing here trusts amounts or plan ids from the payload beyond mapping them
  to rows we created ourselves.
"""
import json
import logging

from django.db import IntegrityError, transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WebhookEvent
from .razorpay_client import (RazorpayNotConfigured, verify_webhook_signature)
from .services import (apply_subscription_entity, record_payment)

logger = logging.getLogger('billing')

# Events we act on. Anything else is stored and marked 'ignored' so that new
# Razorpay event types show up in the admin instead of vanishing.
HANDLED = {
    'subscription.authenticated',
    'subscription.activated',
    'subscription.charged',
    'subscription.updated',
    'subscription.pending',
    'subscription.halted',
    'subscription.paused',
    'subscription.resumed',
    'subscription.cancelled',
    'subscription.completed',
    'payment.failed',
}


@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(APIView):
    """POST /api/billing/webhook/razorpay/

    Must stay unauthenticated — Razorpay cannot present a JWT. The signature
    is the authentication.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        raw_body = request.body
        signature = request.headers.get('X-Razorpay-Signature', '')

        try:
            valid = verify_webhook_signature(raw_body, signature)
        except RazorpayNotConfigured as exc:
            logger.error("billing: webhook rejected — %s", exc)
            return Response({'detail': str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if not valid:
            logger.warning("billing: webhook signature mismatch from %s",
                           request.META.get('REMOTE_ADDR'))
            return Response({'detail': 'Invalid signature.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            body = json.loads(raw_body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return Response({'detail': 'Malformed JSON.'},
                            status=status.HTTP_400_BAD_REQUEST)

        event_type = body.get('event', '')
        # Razorpay sends a stable id per event; fall back to a deterministic key
        # so a missing header still cannot double-apply.
        event_id = request.headers.get('X-Razorpay-Event-Id') or (
            f"{event_type}:{body.get('created_at')}:"
            f"{_entity_id(body)}")

        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(
                    event_id=event_id, event=event_type, payload=body)
        except IntegrityError:
            # Already delivered. Acknowledge so Razorpay stops retrying.
            logger.info("billing: duplicate webhook %s ignored", event_id)
            return Response({'status': 'duplicate'}, status=status.HTTP_200_OK)

        if event_type not in HANDLED:
            event.mark('ignored')
            return Response({'status': 'ignored'}, status=status.HTTP_200_OK)

        try:
            company = self._handle(event_type, body)
        except Exception as exc:  # noqa: BLE001 - we want the retry
            logger.exception("billing: webhook %s failed", event_type)
            event.mark('failed', error=str(exc))
            # 500 tells Razorpay to retry with backoff.
            return Response({'status': 'error'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if company is not None:
            event.company = company
        event.mark('processed')
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)

    # -- handlers ---------------------------------------------------------

    def _handle(self, event_type, body):
        payload = body.get('payload') or {}
        sub_entity = (payload.get('subscription') or {}).get('entity') or {}
        pay_entity = (payload.get('payment') or {}).get('entity') or {}

        if event_type == 'payment.failed':
            if pay_entity:
                record = record_payment(pay_entity, sub_entity or None)
                return record.company if record else None
            return None

        subscription = None
        if sub_entity:
            subscription = apply_subscription_entity(sub_entity)

        # `subscription.charged` is the only event that carries money.
        if pay_entity:
            record_payment(pay_entity, sub_entity or None)

        return subscription.company if subscription else None


def _entity_id(body):
    payload = body.get('payload') or {}
    for key in ('subscription', 'payment'):
        entity = (payload.get(key) or {}).get('entity') or {}
        if entity.get('id'):
            return entity['id']
    return 'unknown'
