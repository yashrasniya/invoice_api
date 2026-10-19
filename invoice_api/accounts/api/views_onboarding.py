"""`onboarding/` — the first-run checklist shown on the app's Home screen.

Progress is derived from real data (customers, invoices, shares) so a step ticks itself the moment the work is
done, from any device. Only two facts are stored: that the user dismissed the list, and that a first invoice was
shared (a PDF handed to the OS share sheet leaves no other server-side trace).
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bill_share.models import BillShare
from companies.models import Customers
from invoice.models import Invoice
from invoice_api.scoping import user_scope_q


class Onboarding(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _company(request):
        return getattr(request, 'company', None) or request.user.user_company

    def get(self, request):
        company = self._company(request)
        # a teammate who joined an existing company has nothing to set up; only its admin sees the list
        if company is None or not request.user.is_company_admin:
            return Response({'visible': False, 'steps': []})

        scope = user_scope_q(request)
        steps = [
            ('company', 'Add company details', True),
            ('customer', 'Add your first customer', Customers.objects.filter(scope).exists()),
            ('invoice', 'Create your first invoice', Invoice.objects.filter(scope, invoice_type='sales').exists()),
            ('share', 'Send it to a customer',
             bool(company.first_invoice_shared_at) or BillShare.objects.filter(scope).exists()),
        ]
        done = all(d for _, _, d in steps)
        return Response({
            'visible': not done and company.onboarding_dismissed_at is None,
            'steps': [{'key': k, 'title': t, 'done': d} for k, t, d in steps],
        })

    def post(self, request):
        company = self._company(request)
        if company is None or not request.user.is_company_admin:
            return Response({'detail': 'Only a company admin can update setup progress.'}, status=403)
        now = timezone.now()
        if request.data.get('dismiss'):
            company.onboarding_dismissed_at = company.onboarding_dismissed_at or now
        if request.data.get('shared'):
            company.first_invoice_shared_at = company.first_invoice_shared_at or now
        company.save(update_fields=['onboarding_dismissed_at', 'first_invoice_shared_at'])
        return self.get(request)
