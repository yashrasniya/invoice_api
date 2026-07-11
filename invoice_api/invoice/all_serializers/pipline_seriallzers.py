
from rest_framework import serializers


class InvoiceUploadSerializer(serializers.Serializer):
    file = serializers.FileField()