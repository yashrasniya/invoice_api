"""Preflight for sqlite_to_postgres.sh: list values PostgreSQL will reject but SQLite accepted.

SQLite does not enforce varchar length, so old rows can exceed a CharField's max_length.
Reads the JSON dump named by $DUMP. Exits 1 if anything is over-length.
"""
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "invoice_api.settings")
django.setup()

from django.apps import apps  # noqa: E402
from django.db import models  # noqa: E402

with open(os.environ["DUMP"]) as fh:
    objects = json.load(fh)

bad = 0
for obj in objects:
    model = apps.get_model(obj["model"])
    for field in model._meta.concrete_fields:
        # FileField/ImageField are varchar(max_length) columns but not CharField subclasses
        if isinstance(field, (models.CharField, models.FileField)) and field.max_length \
                and field.name in obj["fields"]:
            value = obj["fields"][field.name]
            if isinstance(value, str) and len(value) > field.max_length:
                bad += 1
                print(f"OVER-LENGTH {obj['model']} pk={obj['pk']} {field.name}: "
                      f"{len(value)} > {field.max_length} value={value[:60]!r}")

print(f"{bad} over-length value(s)" if bad else "no over-length values")
sys.exit(1 if bad else 0)
