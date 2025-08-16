import io
import datetime

from django.http import FileResponse, HttpResponse
from rest_framework.response import Response

from invoice.serializers import InvoiceSerializerForPDF, InvoiceSerializerForCSV
from submit import Submit
from yaml_manager.models import Yaml
from yaml_reader import YamalReader, FillValue
import pandas as pd


def pdf_generator(qs,request):
    yaml_obj = Yaml.objects.filter(user=request.user)
    if not yaml_obj:
        return Response({"message": "configuration not found"}, 404)
    file_data = []
    for obj in qs:
        if not obj: return Response({"status": 404}, 404)
        ser_obj = InvoiceSerializerForPDF(obj)
        ser_obj.Meta.depth = 1
        data = YamalReader(yaml_obj.first().yaml_file.file)
        fill_obj = FillValue(ser_obj.data, data)
        file_data.append(fill_obj.collect_all_data())
    pdf_data = Submit(file_data, bill_image=str(yaml_obj.first().pdf_template.file)).draw_header_data()
    pdf_file = io.BytesIO(pdf_data)
    pdf_file.seek(0)
    response = FileResponse(pdf_file, as_attachment=True,
                            filename=f"{request.user.username}_{datetime.datetime.now().date()}.pdf")
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