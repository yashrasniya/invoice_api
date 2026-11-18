from rest_framework import serializers

from upi_qr import is_valid_upi_id
from ..gst_utils import STATE_CODES, gstin_error, parse_gstin, state_code_for_name
from ..models import UserCompanies

class UserCompaniesSerializer(serializers.ModelSerializer):
    subscriptions_plan = serializers.IntegerField(read_only=True)
    company_logo = serializers.FileField(required=False,)
    class Meta:
        model = UserCompanies
        fields = "__all__"
        # Switched in UI Config -> Invoice Fields (invoice-header-config/). It
        # must stay out of this full-update endpoint: a form post that omits an
        # unticked checkbox reads as "off" to DRF, so every profile save would
        # otherwise silently switch the feature off.
        read_only_fields = ('enable_line_item_images',)

    def validate_upi_id(self, value):
        # A typo'd VPA produces a QR that fails only inside the payer's bank
        # app, long after the invoice has gone out — reject it at save time.
        if not value:
            return value
        value = value.strip()
        if not is_valid_upi_id(value):
            raise serializers.ValidationError(
                "Enter a valid UPI id in the form name@bank, e.g. acme@okaxis.")
        return value

    def validate_pincode(self, value):
        value = (value or '').strip()
        if value and not (len(value) == 6 and value.isdigit() and value[0] != '0'):
            raise serializers.ValidationError('A PIN code is 6 digits.')
        return value

    def validate(self, attrs):
        attrs = self._resolve_gst_and_state(attrs)
        self._check_lut(attrs)
        upi_id = attrs.get('upi_id', getattr(self.instance, 'upi_id', None))
        if attrs.get('show_upi_qr') and not upi_id:
            raise serializers.ValidationError(
                {'upi_id': "Add a UPI id before enabling the invoice QR code."})
        return attrs

    def _check_lut(self, attrs):
        """A LUT needs its number and the period it covers (one financial year)."""
        cur = lambda k: attrs[k] if k in attrs else getattr(self.instance, k, None)
        number = (cur('lut_number') or '').strip()
        start, end = cur('lut_valid_from'), cur('lut_valid_to')
        if 'lut_number' in attrs:
            attrs['lut_number'] = number
        if not (number or start or end):
            return
        if not (number and start and end):
            raise serializers.ValidationError(
                {'lut_number': 'Enter the LUT number and both dates it is valid for.'})
        if end < start:
            raise serializers.ValidationError({'lut_valid_to': "The end date can't be before the start date."})

    def _resolve_gst_and_state(self, attrs):
        """GST number is optional; the state is not.

        A valid GSTIN fixes the state (its first two digits), so the state fields are derived from it. Without
        one (unregistered / composition sellers) the state is still needed to split CGST/SGST vs IGST, so it
        must be supplied by name or code.
        """
        touched = {'company_gst_number', 'state', 'state_code'} & set(attrs)
        if self.instance is not None and not touched:
            return attrs

        def current(key):
            if key in attrs:
                return attrs[key]
            return getattr(self.instance, key, None)

        gst = (current('company_gst_number') or '').strip()
        state = (current('state') or '').strip()
        code = current('state_code')

        if gst:
            try:
                gst, derived = parse_gstin(gst)
            except ValueError as exc:
                raise serializers.ValidationError({'company_gst_number': str(exc)})
            # pattern alone lets a single mistyped character through
            typo = gstin_error(gst)
            if typo:
                raise serializers.ValidationError({'company_gst_number': typo})
            if code != derived or not state:
                state = STATE_CODES[derived]
            attrs.update(company_gst_number=gst, state_code=derived, state=state)
            return attrs

        if code in (None, ''):
            code = state_code_for_name(state)
            if code is None:
                raise serializers.ValidationError({'state': 'Select your state.'})
        elif int(code) not in STATE_CODES:
            raise serializers.ValidationError({'state_code': 'Not a valid GST state code.'})
        attrs.update(company_gst_number=None, state_code=int(code), state=STATE_CODES[int(code)])
        return attrs
