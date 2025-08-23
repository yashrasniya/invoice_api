import json

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from companies.models import Customers


class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def add_arguments(self, parser):
        parser.add_argument("file_name", nargs="+", type=str)

    def handle(self, *args, **options):
        with open(options["file_name"][0], "r") as r:
            data = json.load(r)
        for i in data:i["product"] = json.loads(i.get("product"))

        for i in data:
            obj=Customers.objects.filter(name=i["name"])
            if not obj:

                obj = Customers(name=i["name"], user=User.objects.first(), gst_number=i["gst_num"], address=i["address"])
                obj.save()
            else:
                obj=obj.first()
