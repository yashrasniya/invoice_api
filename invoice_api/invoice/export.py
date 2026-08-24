import io
import datetime
import logging
import traceback

from django.http import FileResponse, HttpResponse
from django.template.loader import render_to_string
from rest_framework.response import Response

from invoice.serializers import InvoiceSerializerForPDF, InvoiceSerializerForCSV
from submit import Submit
from yaml_manager.models import Yaml
from yaml_reader import YamalReader, FillValue
from yaml_reader import num2words
from upi_qr import company_upi_link, make_qr_data_uri
from pdf_fonts import inject_font_css
import pandas as pd

loger = logging.getLogger(__name__)


class TemplateProps(dict):
    """A template context dict where an unknown key renders empty.

    The keys here are user-defined — product column names, custom header
    fields — so a template can legitimately reference one that a given invoice
    does not carry. Django tolerates that for a plain `{{ x.missing }}` but NOT
    for a filter argument: `{{ item.rate|default:item.amount }}` resolves
    `item.amount` strictly and raises VariableDoesNotExist, which aborted the
    entire PDF over a single unrecognised name. Returning '' keeps the rest of
    the invoice renderable.

    Only __getitem__ is affected; .get() still reports a missing key as None,
    so calculation code that distinguishes absent from empty is unchanged.
    """

    def __missing__(self, key):
        return ''

def pdf_generator(qs, request, return_bytes=False,template_id=None):
    yaml_obj = Yaml.objects.filter(company=request.user.user_company.id)
    if template_id:
        yaml_obj = yaml_obj.filter(id = template_id)
    if not yaml_obj:
        return Response({"message": "configuration not found"}, 404)
        
    template_obj = yaml_obj.first()
    
    if template_obj.is_html:
        import re
        from django.template import Context, Template
        
        try:
            template_obj.yaml_file.file.seek(0)
            raw_html = template_obj.yaml_file.file.read().decode('utf-8')
            
            body_match = re.search(r'<body[^>]*>(.*?)</body>', raw_html, re.IGNORECASE | re.DOTALL)
            if body_match:
                inner_html = body_match.group(1)
            else:
                inner_html = raw_html
        except Exception as e:
            loger.error(f"Error reading HTML file: {e}")
            inner_html = ""
        pages_html = ""
        for obj in qs:
            ser_obj = InvoiceSerializerForPDF(obj)
            invoice_data = TemplateProps(ser_obj.data)
            
            # The serializer carries `receiver` as a bare id, so the customer
            # block of a template would otherwise have nothing to print.
            if obj.receiver:
                invoice_data['receiver_name'] = obj.receiver.name
                invoice_data['receiver_address'] = obj.receiver.address or ''
                invoice_data['receiver_gst_number'] = obj.receiver.gst_number or ''
                invoice_data['receiver_phone'] = obj.receiver.phone_number or ''
                invoice_data['receiver_state'] = obj.receiver.state or ''
                invoice_data['receiver_state_code'] = obj.receiver.state_code or ''

            invoice_data['payment_method'] = (obj.get_payment_method_display()
                                              if obj.payment_method else '')
            invoice_data['payment_status'] = obj.get_payment_status_display()

            custom_header = invoice_data.get('custom_header_field')
            if isinstance(custom_header, str):
                import json
                try:
                    custom_header = json.loads(custom_header)
                except Exception:
                    custom_header = {}
            if not isinstance(custom_header, dict):
                custom_header = {}
            invoice_data['custom_header_field'] = custom_header
            for k, v in custom_header.items():
                invoice_data[k] = v
                invoice_data[k.lower()] = v
                    
            for p in invoice_data.get('products', []):
                props = TemplateProps()
                total = 1.0
                extra_cal = 0.0
                
                # First pass: sort and calculate
                sorted_props = sorted(
                    p.get('product_properties', []),
                    key=lambda x: (
                        1 if x.get('new_product_in_frontend', {}).get('formula') else 0
                    )
                )
                
                calc_results = {}
                for prop in sorted_props:
                    config = prop.get('new_product_in_frontend', {})
                    title = config.get('input_title', '').lower()
                    val_raw = prop.get('value')
                    
                    try: val = float(val_raw) if val_raw else 0.0
                    except: val = 0.0
                    
                    calculated_val = val_raw
                    
                    if config.get('is_calculable'):
                        formula = config.get('formula')
                        on_without_gst = config.get('on_with_out_gst_amount', False)
                        
                        if formula:
                            if formula == '+':
                                if on_without_gst: extra_cal += val
                                else: total += val
                                calculated_val = val
                            elif formula == '-':
                                if on_without_gst: extra_cal -= val
                                else: total -= val
                                calculated_val = val
                            elif formula == '/':
                                total /= val if val != 0 else 1.0
                                calculated_val = val
                            elif formula == '%+':
                                calculated_val = (val / 100) * total
                                if on_without_gst: extra_cal += calculated_val
                                else: total += calculated_val
                            elif formula == '%-':
                                calculated_val = (val / 100) * total
                                if on_without_gst: extra_cal -= calculated_val
                                else: total -= calculated_val
                        else:
                            if val_raw and title != 'gst':
                                total *= val
                                calculated_val = val_raw
                                
                    calc_results[config.get('id')] = calculated_val
                    
                # Second pass: populate props for template
                for prop in p.get('product_properties', []):
                    config = prop.get('new_product_in_frontend', {})
                    title = config.get('input_title', '').lower()
                    
                    if config.get('show_calculated_value'):
                        display_val = calc_results.get(config.get('id'), prop.get('value'))
                        try:
                            display_val = f"{float(display_val):.2f}"
                        except:
                            pass
                    else:
                        display_val = prop.get('value')
                        
                    props[title] = display_val
                    for word in title.split():
                        props[word] = display_val
                
                # `amount`/`total` only exist as props if the user happened to
                # name a product column that way; templates ask for them
                # regardless. Fall back to the line total the product already
                # carries so the amount column shows a figure, not a blank.
                for alias in ('amount', 'total'):
                    if not props.get(alias):
                        props[alias] = p.get('total_amount')

                p['props'] = props
                
            django_template = Template(inner_html)
            
            company_data = {}
            if request.user.user_company:
                company = request.user.user_company
                company_data = {
                    'company_name': company.company_name,
                    'company_address': company.company_address or '',
                    'company_gst_number': company.company_gst_number or '',
                    'company_state': company.state or '',
                    'company_state_code': company.state_code or '',
                    'company_email_id': company.company_email_id or '',
                    'bank_name': company.bank_name or '',
                    'account_number': company.account_number or '',
                    'branch': company.branch or '',
                    'ifsc_code': company.ifsc_code or '',
                }
                if request.user.user_company.company_logo:
                    company_data['company_logo'] = request.build_absolute_uri(request.user.user_company.company_logo.url)
            

            
            total_amount_with_gst = float(invoice_data.get('total_final_amount') or 0)
            total_gst_amount_acc = float(invoice_data.get('gst_final_amount') or 0)
            total_taxable_amount = total_amount_with_gst - total_gst_amount_acc

            footer_data = {}
            footer_data["total_amount_with_out_gst"] = round(total_taxable_amount, 2)
            footer_data["gst_amount"] = round(total_gst_amount_acc, 2)
            footer_data["total_amount_with_gst"] = round(total_amount_with_gst, 2)
            footer_data["total_amount_in_text"] = num2words(round(total_amount_with_gst, 2))
            footer_data["center_gst_amount"] = round(total_gst_amount_acc / 2, 2)
            footer_data["state_gst_amount"] = round(total_gst_amount_acc / 2, 2)
            
            avg_gst = (total_gst_amount_acc / total_taxable_amount * 100) if total_taxable_amount else 0
            footer_data["gst"] = round(avg_gst, 2)
            footer_data["center_gst"] = round(avg_gst / 2, 2)
            footer_data["state_gst"] = round(avg_gst / 2, 2)

            # The QR encodes this invoice's grand total, so it is built per
            # page rather than once per request. As a data: URI it survives
            # WeasyPrint rendering a bare string with no asset base URL.
            upi_link = company_upi_link(
                request.user.user_company,
                total_amount_with_gst,
                note=invoice_data.get('invoice_number') or None,
            )
            # upi_id rides on the same gate as the QR: one toggle controls the
            # whole payment block, so a template can never print the VPA next
            # to a QR that isn't there.
            company_data['upi_id'] = (request.user.user_company.upi_id
                                      if upi_link else '') or ''
            company_data['upi_link'] = upi_link or ''
            company_data['upi_qr'] = make_qr_data_uri(upi_link) or ''

            context_dict = {
                'invoice': invoice_data,
                'company': company_data,
                'footer': footer_data
            }
            custom_header = invoice_data.get('custom_header_field')
            if isinstance(custom_header, str):
                import json
                try:
                    custom_header = json.loads(custom_header)
                except Exception:
                    custom_header = {}
            if not isinstance(custom_header, dict):
                custom_header = {}
            invoice_data['custom_header_field'] = custom_header
            for k, v in custom_header.items():
                context_dict[k] = v
                context_dict[k.lower()] = v
            context = Context(context_dict)
            
            products = invoice_data.get("products", [])
            products_data = []
            for i in products:
                products_data.append(i['props'])

            context['products_data'] = products_data
            rendered_inner = django_template.render(context)
            pages_html += f'<div style="position: relative; width: 595px; height: 842px; page-break-after: always; overflow: hidden; background: white;">\n{rendered_inner}\n</div>\n'

        full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Invoice PDF</title>
<style>
    @page {{ size: 595px 842px; margin: 0; }}
    body {{ margin: 0; padding: 0; background: white; }}
    * {{ box-sizing: border-box; }}
</style>
</head>
<body>
{pages_html}
</body>
</html>"""
        
        try:
            import weasyprint
            # presentational_hints: honour plain HTML sizing attributes such as
            # <img height="50">. Without it WeasyPrint ignores them, so an
            # unsized image keeps its intrinsic pixel size and gets silently
            # dropped when it no longer fits the fixed-height page box. Author
            # CSS still wins — hints only fill in where no rule applies.
            #
            # inject_font_css: the bundled Devanagari face has to be declared
            # inside the document. WeasyPrint only registers the @font-face
            # files it sees while parsing the HTML, so the same CSS handed to
            # write_pdf(stylesheets=…) is ignored and Hindi keeps rendering
            # blank on any host that has no Devanagari font of its own.
            pdf_file_bytes = weasyprint.HTML(
                string=inject_font_css(full_html)).write_pdf(
                presentational_hints=True)
            pdf_file = io.BytesIO(pdf_file_bytes)
            pdf_file.seek(0)
            
            if return_bytes:
                return pdf_file
            return FileResponse(pdf_file, as_attachment=True,
                                filename=f"{request.user.username}_{datetime.datetime.now().date()}.pdf")
        except Exception as e:
            loger.error(e)
            loger.debug(traceback.print_exc())
            if return_bytes:
                return None
            return FileResponse('Something went wrong', as_attachment=True, filename="error.pdf")

    file_data = []
    try:
        for obj in qs:
            if not obj: return Response({"status": 404}, 404)
            ser_obj = InvoiceSerializerForPDF(obj)
            loger.debug(f"start working on {obj}")
            ser_obj.Meta.depth = 1
            template_obj = yaml_obj.first()
            template = YamalReader(template_obj.yaml_file.file,auto_scale=template_obj.auto_scale)
            fill_obj = FillValue(ser_obj.data, template)
            print(request.user.user_company.company_logo)
            fill_obj.set_my_company_data(request)
            file_data.append(fill_obj)
        try:
            pdf_name = qs.first().receiver.name
        except Exception as e:
            pdf_name = "GST Invoice"

        bill_template = ''
        if yaml_obj.first().pdf_template:
            bill_template = str(yaml_obj.first().pdf_template.file)
        pdf_data = Submit(file_data, bill_image=bill_template,pdf_name=pdf_name).draw_header_data()
        loger.debug(f"{pdf_name} Done {len(pdf_data)}")
        pdf_file = io.BytesIO(pdf_data)
        pdf_file.seek(0)
        if return_bytes:
            return pdf_file
        response = FileResponse(pdf_file, as_attachment=True,
                                filename=f"{request.user.username}_{datetime.datetime.now().date()}.pdf")
    except Exception as e:
        loger.error(e)
        loger.debug(traceback.print_exc())
        if return_bytes:
            return None
        return FileResponse('Some thing went wrong', as_attachment=True,
                                filename=f"error.pdf")
    return response


def csv_generator(qs, request):
    # Serialize the queryset
    ser_obj = InvoiceSerializerForCSV(qs, many=True)
    data_list = ser_obj.data  # This will be a list of dictionaries

    # Convert to DataFrame
    df = pd.DataFrame(data_list)

    # If you want to rename or reorder columns, you can do it here
    # Example: df = df[["invoice_number", "receiver", "date", "total_final_amount"]]
    # Example: df.rename(columns={"receiver": "Customer Name"}, inplace=True)

    # Generate CSV in-memory
    csv_data = df.to_csv(index=False)

    # Prepare the HTTP response
    response = HttpResponse(
        content=csv_data,
        content_type='text/csv'
    )
    response['Content-Disposition'] = 'attachment; filename="invoices_export.csv"'
    return response

def pdf_data_generator(qs, request):
    ser_obj = InvoiceSerializerForCSV(qs, many=True)
    data_list = ser_obj.data

    total_final = sum([float(item.get('total_final_amount') or 0) for item in data_list])
    total_gst = sum([float(item.get('gst_final_amount') or 0) for item in data_list])

    context = {
        'invoices': data_list,
        'total_final': round(total_final, 2),
        'total_gst': round(total_gst, 2),
        'report_date': datetime.datetime.now().strftime('%Y-%m-%d')
    }

    html_string = render_to_string('html_template_one.html', context)
    import weasyprint
    pdf_file = weasyprint.HTML(
        string=inject_font_css(html_string)).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="invoices_export_data.pdf"'
    return response