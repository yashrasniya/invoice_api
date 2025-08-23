import io
import datetime
import logging
import traceback

from django.http import FileResponse, HttpResponse
from rest_framework.response import Response

from invoice.serializers import InvoiceSerializerForPDF, InvoiceSerializerForCSV
from submit import Submit
from yaml_manager.models import Yaml
from yaml_reader import YamalReader, FillValue
import pandas as pd

loger = logging.getLogger(__name__)

def pdf_generator(qs, request, return_bytes=False,template_id=None):
    yaml_obj = Yaml.objects.filter(company=request.user.user_company.id)
    if template_id:
        yaml_obj = yaml_obj.filter(id = template_id)
    if not yaml_obj:
        return Response({"message": "configuration not found"}, 404)
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