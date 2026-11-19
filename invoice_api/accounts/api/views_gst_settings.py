"""The company's GST filing settings, for clients without the full company form.

GET   → GSTIN, state, filing frequency, LUT and the dispatch-from city / PIN
        code of e-way bills, and whether e-way bills show at all; any member of the company (the reports need them).
PATCH → those settings only (not GSTIN or state); company admins only. Validation is the
        company serializer's (a LUT needs its number and both dates).
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers.UserCompanies import UserCompaniesSerializer

READ_FIELDS = ('company_gst_number', 'state', 'state_code', 'gst_filing_frequency',
               'lut_number', 'lut_valid_from', 'lut_valid_to', 'city', 'pincode', 'enable_eway_bill')
EDIT_FIELDS = ('gst_filing_frequency', 'lut_number', 'lut_valid_from', 'lut_valid_to', 'city', 'pincode',
               'enable_eway_bill')


def _out(company):
    data = UserCompaniesSerializer(company).data
    return {k: data.get(k) for k in READ_FIELDS}


class CompanyGstSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        company = request.user.user_company
        if company is None:
            return Response({'detail': 'Set up your company first.'}, status=status.HTTP_404_NOT_FOUND)
        is_admin = (request.user.is_company_admin or
                    'role.manage' in (getattr(request, 'permissions', None) or set()))
        return Response({**_out(company), 'can_edit': bool(is_admin)})

    def patch(self, request):
        company = request.user.user_company
        if company is None:
            return Response({'detail': 'Set up your company first.'}, status=status.HTTP_404_NOT_FOUND)
        is_admin = (request.user.is_company_admin or
                    'role.manage' in (getattr(request, 'permissions', None) or set()))
        if not is_admin:
            return Response({'detail': 'Only a company admin can change GST settings.',
                             'code': 'permission_denied'}, status=status.HTTP_403_FORBIDDEN)
        unknown = set(request.data) - set(EDIT_FIELDS)
        if unknown:
            return Response({'detail': f"Only {', '.join(EDIT_FIELDS)} can be changed here."},
                            status=status.HTTP_400_BAD_REQUEST)
        # blank dates clear the LUT
        data = {k: (None if k.startswith('lut_valid') and v in ('', None) else v) for k, v in request.data.items()}
        ser = UserCompaniesSerializer(company, data=data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        company.refresh_from_db()
        return Response({**_out(company), 'can_edit': True})
