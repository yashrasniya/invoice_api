"""
Tests for the company UPI id and the amount-bearing invoice QR code.

The QR is the only part of an invoice a customer acts on with real money, so
the cases that matter are the ones where it must NOT be drawn: no opt-in, a
malformed VPA, or a total that would produce a link the payer's bank app
rejects.
"""
import base64
import re
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from rest_framework.test import APITestCase

from accounts.models import User, UserCompanies
from accounts.serializers.UserCompanies import UserCompaniesSerializer
from upi_qr import (build_upi_link, company_upi_link, is_valid_upi_id,
                    make_qr_data_uri, make_qr_image)


def params(link):
    return {k: v[0] for k, v in parse_qs(urlparse(link).query).items()}


class UpiLinkTests(TestCase):

    def test_valid_ids_accepted(self):
        for vpa in ('acme@okaxis', 'yash.rasniya-3@ybl', 'a_b@upi', '9876543210@paytm'):
            self.assertTrue(is_valid_upi_id(vpa), vpa)

    def test_malformed_ids_rejected(self):
        for vpa in ('', None, 'no-at-sign', '@okaxis', 'acme@', 'acme@1234',
                    'acme@ok axis', 'a@b', 'acme@okaxis@ybl', '.acme@okaxis'):
            self.assertFalse(is_valid_upi_id(vpa), vpa)

    def test_link_carries_amount_and_currency(self):
        p = params(build_upi_link('acme@okaxis', 'Acme', 1180, 'INV-1'))
        self.assertEqual(p['pa'], 'acme@okaxis')
        self.assertEqual(p['pn'], 'Acme')
        self.assertEqual(p['am'], '1180.00')
        self.assertEqual(p['cu'], 'INR')
        self.assertEqual(p['tn'], 'INV-1')

    def test_amount_always_two_decimals(self):
        self.assertEqual(params(build_upi_link('a@ok', amount=7))['am'], '7.00')
        self.assertEqual(params(build_upi_link('a@ok', amount='1234.5'))['am'], '1234.50')
        # rounds rather than truncating, so the QR never asks for less than due
        self.assertEqual(params(build_upi_link('a@ok', amount=10.005))['am'], '10.01')

    def test_no_link_without_a_collectable_amount(self):
        for amount in (None, 0, -50, 'abc', ''):
            self.assertIsNone(build_upi_link('acme@okaxis', amount=amount), amount)

    def test_no_link_for_invalid_vpa(self):
        self.assertIsNone(build_upi_link('not-a-vpa', amount=100))

    def test_special_characters_are_url_encoded(self):
        link = build_upi_link('acme@okaxis', 'Bell & Sons', 100)
        self.assertIn('pn=Bell%20%26%20Sons', link)
        # the raw ampersand must not split the query into an extra parameter
        self.assertEqual(params(link)['pn'], 'Bell & Sons')

    def test_note_truncated_to_psp_limit(self):
        p = params(build_upi_link('a@ok', amount=1, note='X' * 90))
        self.assertEqual(len(p['tn']), 50)


class QrRenderTests(TestCase):

    def test_data_uri_is_a_decodable_png(self):
        uri = make_qr_data_uri(build_upi_link('acme@okaxis', 'Acme', 500))
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        raw = base64.b64decode(uri.split(',', 1)[1])
        self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')

    def test_no_qr_without_a_link(self):
        self.assertIsNone(make_qr_image(None))
        self.assertIsNone(make_qr_data_uri(None))

    def test_qr_decodes_back_to_the_link(self):
        """The whole feature rests on this: the printed code must scan.

        Neither decoder is a project dependency (zbar needs a native lib,
        opencv is ~90MB), so this runs opportunistically wherever one of them
        happens to be installed.
        """
        link = build_upi_link('acme@okaxis', 'Acme', 1180, 'INV-1')
        img = make_qr_image(link)
        try:
            from pyzbar.pyzbar import decode
            self.assertEqual(decode(img)[0].data.decode(), link)
            return
        except ImportError:
            pass
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('no QR decoder available (pyzbar or opencv)')
        # also check the size the PDF actually prints it at — downscaling a QR
        # with a smoothing filter is what usually breaks scannability
        for size in (img.size, (208, 208)):
            from PIL import Image as PILImage
            arr = np.array(img.resize(size, PILImage.NEAREST).convert('RGB'))
            decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(
                cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
            self.assertEqual(decoded, link, f"failed at {size}")


class CompanyOptInTests(TestCase):

    def setUp(self):
        self.company = UserCompanies.objects.create(
            company_name='Acme', is_varified=True,
            upi_id='acme@okaxis', show_upi_qr=True)

    def test_link_built_for_opted_in_company(self):
        p = params(self.company.upi_payment_link(1180, note='INV-9'))
        self.assertEqual(p['pa'], 'acme@okaxis')
        self.assertEqual(p['am'], '1180.00')
        self.assertEqual(p['pn'], 'Acme')

    def test_saved_upi_id_stays_off_invoices_until_opted_in(self):
        self.company.show_upi_qr = False
        self.company.save()
        self.assertIsNone(self.company.upi_payment_link(1180))

    def test_no_link_when_no_upi_id(self):
        self.company.upi_id = None
        self.company.save()
        self.assertIsNone(self.company.upi_payment_link(1180))

    def test_no_company_no_link(self):
        self.assertIsNone(company_upi_link(None, 1180))

    def test_defaults_are_off(self):
        plain = UserCompanies.objects.create(company_name='Plain')
        self.assertFalse(plain.show_upi_qr)
        self.assertIsNone(plain.upi_payment_link(1180))


class CompanySerializerTests(APITestCase):

    base = {'company_name': 'Acme', 'company_address': 'MG Road',
            'company_gst_number': '22AAAAA0000A1Z5', 'state': 'Karnataka',
            'state_code': 29, 'company_email_id': 'a@acme.com'}

    def test_valid_upi_id_saves(self):
        ser = UserCompaniesSerializer(data={**self.base, 'upi_id': 'acme@okaxis',
                                            'show_upi_qr': True})
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertTrue(ser.save().show_upi_qr)

    def test_malformed_upi_id_rejected(self):
        ser = UserCompaniesSerializer(data={**self.base, 'upi_id': 'acme-okaxis'})
        self.assertFalse(ser.is_valid())
        self.assertIn('upi_id', ser.errors)

    def test_qr_cannot_be_enabled_without_an_upi_id(self):
        ser = UserCompaniesSerializer(data={**self.base, 'show_upi_qr': True})
        self.assertFalse(ser.is_valid())
        self.assertIn('upi_id', ser.errors)

    def test_upi_id_is_optional(self):
        ser = UserCompaniesSerializer(data=self.base)
        self.assertTrue(ser.is_valid(), ser.errors)

    def test_whitespace_is_trimmed(self):
        ser = UserCompaniesSerializer(data={**self.base, 'upi_id': '  acme@okaxis '})
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data['upi_id'], 'acme@okaxis')


class TemplatePropsTests(TestCase):
    """A template naming a field this invoice lacks must not kill the export.

    Django resolves filter *arguments* strictly, so `{{ x.rate|default:x.amount }}`
    used to raise VariableDoesNotExist and abort the whole PDF when `amount`
    was not one of the user's product columns.
    """

    def setUp(self):
        from invoice.export import TemplateProps
        self.props = TemplateProps({'description': 'Widget', 'quantity': '5'})

    def test_known_key_returned(self):
        self.assertEqual(self.props['description'], 'Widget')

    def test_unknown_key_renders_empty(self):
        self.assertEqual(self.props['amount'], '')
        self.assertEqual(self.props['anything at all'], '')

    def test_get_still_reports_absence(self):
        # calculation code must still be able to tell absent from empty
        self.assertIsNone(self.props.get('amount'))

    def test_strict_filter_argument_no_longer_raises(self):
        from django.template import Context, Template
        tpl = Template('[{{ item.rate|default:item.amount }}]')
        # a plain dict is what used to blow up
        with self.assertRaises(Exception):
            tpl.render(Context({'item': {'description': 'Widget'}}))
        self.assertEqual(tpl.render(Context({'item': self.props})), '[]')

    def test_missing_key_does_not_mask_present_one(self):
        from django.template import Context, Template
        tpl = Template('{{ item.quantity|default:item.amount }}')
        self.assertEqual(tpl.render(Context({'item': self.props})), '5')
