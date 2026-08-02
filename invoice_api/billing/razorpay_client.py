"""Razorpay client factory and signature verification.

Everything that talks to Razorpay goes through here so that credentials are
read in exactly one place and tests can patch a single symbol.
"""
import hashlib
import hmac
import logging

from django.conf import settings

logger = logging.getLogger('billing')


class RazorpayNotConfigured(RuntimeError):
    pass


class BillingUnavailable(RuntimeError):
    """A Razorpay API call failed for a reason the caller should surface.

    Carries a message written for the person clicking the button, plus the
    HTTP status the API should return.
    """

    def __init__(self, message, *, status_code=502, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _classify(message: str):
    """Map Razorpay's own error description to (message, status, retryable).

    Returns None when the description is not one we recognise, in which case
    the caller passes it through verbatim. Never invent a diagnosis — a wrong
    explanation is worse than the raw text.
    """
    lowered = (message or '').lower()

    if 'too many requests' in lowered or 'rate limit' in lowered:
        return ("Razorpay is rate-limiting this account. Wait a minute and retry. "
                "If it persists, run `manage.py sync_razorpay_plans` once so plans "
                "are created ahead of time rather than during checkout.",
                429, True)

    if 'not found on the server' in lowered or 'not enabled' in lowered:
        return ("The Subscriptions product is not enabled on this Razorpay account. "
                "Enable it at Dashboard → Subscriptions, then retry.",
                503, False)

    # A bare "Unauthorized" on a Subscriptions route is the product gate, not a
    # bad key: the same credentials authenticate fine against /payments. Do not
    # send people off to re-check their keys — verified with `razorpay_debug`,
    # which shows /payments 200 alongside /plans 401.
    if lowered in ('unauthorized', 'unauthorised') or 'unauthorized' in lowered:
        return ("Razorpay returned 401 Unauthorized for the Subscriptions API. "
                "If other Razorpay calls work, the keys are fine and the "
                "Subscriptions product is simply not activated on this account — "
                "activate it at Dashboard → Subscriptions (test accounts often "
                "need Razorpay support to enable it). Run "
                "`manage.py razorpay_debug` to confirm: it will show /payments "
                "returning 200 while /plans returns 401.",
                503, False)

    if ('authentication failed' in lowered or 'invalid api key' in lowered
            or 'api key' in lowered or 'authentication' in lowered):
        return ("Razorpay rejected the API credentials. Check RAZORPAY_KEY_ID / "
                "RAZORPAY_KEY_SECRET (or the legacy key_id / key_secret) in .env.",
                503, False)

    return None


def razorpay_call(fn, *args, **kwargs):
    """Run a Razorpay SDK call, translating errors into BillingUnavailable.

    Two things this must always do:

    * **Preserve Razorpay's own description.** The SDK's error classes are not
      reliable signals — `client.request` falls through to `ServerError` for
      *any* error code it does not recognise, so "ServerError" frequently means
      "unactivated feature" or "bad credentials" rather than "Razorpay is down".
      Only the description tells you what actually happened.
    * **Log the full exception.** The operator needs the raw text even when the
      user gets a friendly version.
    """
    try:
        import razorpay.errors as rzp_errors
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RazorpayNotConfigured("The `razorpay` package is not installed.") from exc

    known = (rzp_errors.BadRequestError, rzp_errors.GatewayError,
             rzp_errors.ServerError)

    try:
        return fn(*args, **kwargs)

    except known as exc:
        raw = str(exc).strip()
        kind = type(exc).__name__
        logger.error("billing: Razorpay %s — %s", kind, raw or '(no description)')

        classified = _classify(raw)
        if classified:
            message, status_code, retryable = classified
            raise BillingUnavailable(f"{message} (Razorpay said: {raw})",
                                     status_code=status_code,
                                     retryable=retryable) from exc

        if not raw:
            raise BillingUnavailable(
                f"Razorpay returned a {kind} with no description. This usually "
                "means the request never reached the Subscriptions API — check "
                "that Subscriptions is enabled on the account and that the API "
                "keys are correct.",
                status_code=502, retryable=True) from exc

        # Unrecognised: pass Razorpay's wording through untouched.
        raise BillingUnavailable(f"Razorpay error ({kind}): {raw}",
                                 status_code=502,
                                 retryable=kind != 'BadRequestError') from exc

    except Exception as exc:  # network, DNS, TLS, proxy
        logger.exception("billing: unexpected Razorpay failure")
        raise BillingUnavailable(
            f"Could not reach Razorpay ({type(exc).__name__}: {exc}). "
            "Check network access to api.razorpay.com.",
            status_code=502, retryable=True) from exc


def get_credentials():
    key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
    key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
    if not key_id or not key_secret:
        raise RazorpayNotConfigured(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set. "
            "Add them to invoice_api/.env and restart.")
    return key_id, key_secret


def get_client():
    """Return an authenticated Razorpay client.

    Imported lazily so that the app still boots (and unrelated tests still run)
    when the `razorpay` package is absent.
    """
    try:
        import razorpay
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RazorpayNotConfigured(
            "The `razorpay` package is not installed. `pip install razorpay`."
        ) from exc

    key_id, key_secret = get_credentials()
    client = razorpay.Client(auth=(key_id, key_secret))
    client.set_app_details({"title": "invoice_api", "version": "1.0"})
    return client


def is_test_mode() -> bool:
    return getattr(settings, 'RAZORPAY_KEY_ID', '').startswith('rzp_test_')


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _hmac_sha256(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Verify `X-Razorpay-Signature` against the RAW request body.

    Razorpay is explicit that the body must not be parsed or re-serialised
    before hashing, so callers must pass `request.body`, never `request.data`.
    """
    secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
    if not secret:
        raise RazorpayNotConfigured(
            "RAZORPAY_WEBHOOK_SECRET is not set; refusing to accept webhooks.")
    if not signature:
        return False
    expected = _hmac_sha256(secret, raw_body)
    return hmac.compare_digest(expected, signature)


def verify_subscription_payment_signature(subscription_id: str, payment_id: str,
                                          signature: str) -> bool:
    """Verify the handshake Checkout returns after a successful authorisation.

    For subscriptions the signed message is `payment_id|subscription_id`
    (note the order — it is the reverse of the Orders flow).

    This proves the browser callback is genuine. It does NOT prove the money
    settled, so we use it only to trigger an immediate re-sync; entitlement is
    still granted by the webhook.
    """
    _, key_secret = get_credentials()
    if not signature:
        return False
    message = f"{payment_id}|{subscription_id}".encode('utf-8')
    return hmac.compare_digest(_hmac_sha256(key_secret, message), signature)
