"""
Resolve which WhatsApp account a company sends through.

Two modes (chosen per company in WA Settings, `CompanyWhatsAppSettings`):
- 'own'      → the company's connected WhatsApp number
               (plan feature: whatsapp_integration)
- 'platform' → the product's shared account, managed by the Product Owner
               (plan feature: whatsapp_shared_number)

Daily limit: the plan's `sends_per_day` for the mode's feature; for
platform mode the account's `default_daily_limit` is the fallback, for
own mode the fallback is 20.
"""
from invoice_api.limits import get_limit

OWN_FEATURE = 'whatsapp_integration'
PLATFORM_FEATURE = 'whatsapp_shared_number'
OWN_DEFAULT_LIMIT = 20


def get_company_mode(company):
    from .models import CompanyWhatsAppSettings, WhatsAppIntegration
    settings_obj = CompanyWhatsAppSettings.objects.filter(company=company).first()
    if settings_obj:
        return settings_obj.mode
    # legacy default: companies already using their own number keep it
    if WhatsAppIntegration.objects.filter(
            status='active', user__user_company=company).exists():
        return 'own'
    return 'platform'


def resolve_whatsapp_account(request):
    """Returns (mode, creds, daily_limit, error).
    creds = dict(phone_number_id, access_token, default_template_name,
    business_account_id) or None; error = None or
    {'message': str, 'code': 'upgrade_required' | 'config'}."""
    from .models import PlatformWhatsAppAccount, WhatsAppIntegration

    company = getattr(request, 'company', None)
    features = getattr(request, 'features', None) or set()
    if company is None:
        return None, None, 0, {'message': "No company resolved for this request.",
                               'code': 'config'}

    mode = get_company_mode(company)

    if mode == 'own':
        if OWN_FEATURE not in features:
            return mode, None, 0, {
                'message': "Your plan does not include using your own WhatsApp number.",
                'code': 'upgrade_required'}
        integ = (WhatsAppIntegration.objects
                 .filter(status='active', user__user_company=company)
                 .order_by('id').first())
        if not integ or not integ.phone_number_id or not integ.access_token:
            return mode, None, 0, {
                'message': "Your WhatsApp number is not configured or not active. "
                           "Set it up in WhatsApp Settings.",
                'code': 'config'}
        creds = {'phone_number_id': integ.phone_number_id,
                 'access_token': integ.access_token,
                 'default_template_name': integ.default_template_name,
                 'business_account_id': integ.business_account_id}
        limit = get_limit(request, OWN_FEATURE, 'sends_per_day')
        return mode, creds, (OWN_DEFAULT_LIMIT if limit is None else limit), None

    # platform mode
    if PLATFORM_FEATURE not in features:
        return mode, None, 0, {
            'message': "Your plan does not include the shared WhatsApp number.",
            'code': 'upgrade_required'}
    account = PlatformWhatsAppAccount.get_active()
    if not account or not account.phone_number_id or not account.access_token:
        return mode, None, 0, {
            'message': "The product WhatsApp account is not configured. "
                       "Please contact support.",
            'code': 'config'}
    creds = {'phone_number_id': account.phone_number_id,
             'access_token': account.access_token,
             'default_template_name': account.default_template_name,
             'business_account_id': account.business_account_id}
    limit = get_limit(request, PLATFORM_FEATURE, 'sends_per_day')
    return mode, creds, (account.default_daily_limit if limit is None else limit), None
