"""Compare every row and column of the SQLite database with the PostgreSQL copy.

Env: SQLITE_PATH (read-only) and DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT for PostgreSQL.
Run from invoice_api/ with:  PYTHONPATH=. python scripts/verify_postgres_copy.py
Checks per table: same primary keys, same value in every column present on both sides
(booleans, decimals, datetimes and JSON are normalised), plus a full ORM read of every model.
Columns that exist only on the PostgreSQL side (added by newer migrations) are listed, not compared.

Known, accepted differences (these are NOT reported as problems):
  * datetimes are compared to the millisecond: Django's dumpdata JSON encoder drops sub-millisecond digits
  * NULL vs '' (empty string) on text/file columns
  * UUIDs stored as 32 hex chars (SQLite) vs dashed (PostgreSQL)
  * auto-generated many-to-many link tables get new ids, so they are compared as sets of (a, b) pairs
Exits 1 on any difference.
"""
import datetime as dt
import decimal
import json
import os
import re
import sqlite3
import sys
import uuid

import django
import psycopg2

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "invoice_api.settings")
django.setup()

SKIP = {"django_migrations", "django_content_type", "auth_permission", "django_admin_log",
        "django_session", "django_cache"}

lite = sqlite3.connect(f"file:{os.environ['SQLITE_PATH']}?mode=ro", uri=True)
pg = psycopg2.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                      password=os.environ.get("DB_PASSWORD", ""), host=os.environ.get("DB_HOST", "127.0.0.1"),
                      port=os.environ.get("DB_PORT", "5432"))
pgc = pg.cursor()


def norm(v):
    """Make a SQLite value and a PostgreSQL value comparable."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v.hex
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (decimal.Decimal, float)):
        return round(float(v), 6)
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        v = v.astimezone(dt.timezone.utc)
        return v.replace(microsecond=v.microsecond // 1000 * 1000).isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dt.time):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    if isinstance(v, (bytes, memoryview)):
        return bytes(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        # SQLite stores datetimes / JSON / decimals as text; parse the shapes we can recognise.
        if s[:2] in ("{\"", "[{") or s in ("[]", "{}") or s.startswith('["') or s.startswith("[0") or s.startswith("[1"):
            try:
                return json.dumps(json.loads(s), sort_keys=True)
            except ValueError:
                pass
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            if len(s) >= 10 and s[4] == "-" and s[7] == "-" and len(s) > 10:
                return norm(d)
        except ValueError:
            pass
        if re.fullmatch(r"[0-9a-fA-F]{8}-?([0-9a-fA-F]{4}-?){3}[0-9a-fA-F]{12}", s):
            return s.replace("-", "").lower()
        return v
    return v


def same(a, b):
    a, b = norm(a), norm(b)
    return a == b or (a in (None, "") and b in (None, ""))


def pg_cols(table):
    pgc.execute("select column_name from information_schema.columns where table_schema='public' "
                "and table_name=%s order by ordinal_position", (table,))
    return [r[0] for r in pgc.fetchall()]


def pk_of(table, cols):
    return "id" if "id" in cols else cols[0]


problems = 0
tables = [r[0] for r in lite.execute(
    "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1")]
for t in tables:
    if t in SKIP:
        continue
    lcols = [r[1] for r in lite.execute(f'pragma table_info("{t}")')]
    pcols = pg_cols(t)
    if not pcols:
        print(f"MISSING TABLE in PostgreSQL: {t}")
        problems += 1
        continue
    common = [c for c in lcols if c in pcols]
    only_lite = [c for c in lcols if c not in pcols]
    only_pg = [c for c in pcols if c not in lcols]
    if only_lite:
        print(f"{t}: columns only in SQLite (NOT migrated): {only_lite}")
        problems += 1
    sel = ", ".join(f'"{c}"' for c in common)
    pgc.execute(f'select {sel} from "{t}"')
    prows_all = pgc.fetchall()
    lrows_all = list(lite.execute(f'select {sel} from "{t}"'))
    if "id" in common and len(common) == 3:  # auto m2m link table: id + two FK columns
        fk = [i for i, c in enumerate(common) if c != "id"]
        lset = sorted(tuple(norm(r[i]) for i in fk) for r in lrows_all)
        pset = sorted(tuple(norm(r[i]) for i in fk) for r in prows_all)
        lrows = {i: r for i, r in enumerate(lset)}
        prows = {i: r for i, r in enumerate(pset)}
        if lset != pset:
            problems += 1
            print(f"{t}: link pairs differ, only-sqlite={[x for x in lset if x not in pset][:3]} "
                  f"only-pg={[x for x in pset if x not in lset][:3]}")
        print(f"ok   {t}: {len(lset)} links (compared as pairs)" if lset == pset else f"FAIL {t}")
        continue
    pk = pk_of(t, common)
    lrows = {r[common.index(pk)]: r for r in lrows_all}
    prows = {r[common.index(pk)]: r for r in prows_all}
    if set(lrows) != set(prows):
        problems += 1
        print(f"{t}: key mismatch, only-sqlite={sorted(set(lrows) - set(prows))[:5]} "
              f"only-pg={sorted(set(prows) - set(lrows))[:5]}")
    bad_cols = {}
    for k in set(lrows) & set(prows):
        for i, c in enumerate(common):
            if not same(lrows[k][i], prows[k][i]):
                bad_cols.setdefault(c, []).append((k, lrows[k][i], prows[k][i]))
    for c, items in bad_cols.items():
        problems += 1
        k, a, b = items[0]
        print(f"{t}.{c}: {len(items)} differing value(s), e.g. pk={k} sqlite={a!r:.60} postgres={b!r:.60}")
    note = f" (new PG-only columns: {only_pg})" if only_pg else ""
    print(f"ok   {t}: {len(lrows)} rows{note}" if not bad_cols and set(lrows) == set(prows) and not only_lite else f"FAIL {t}")

# every model must be fully readable through the ORM (catches bad types / broken FKs)
from django.apps import apps  # noqa: E402

orm_bad = 0
for model in apps.get_models():
    try:
        n = sum(1 for _ in model._base_manager.all().iterator())
    except Exception as exc:  # noqa: BLE001
        orm_bad += 1
        print(f"ORM READ FAILED {model._meta.label}: {exc}")
print(f"ORM read of all {len(apps.get_models())} models: {'FAILED for %d' % orm_bad if orm_bad else 'ok'}")

problems += orm_bad
print("\nVERIFY: ALL OK" if not problems else f"\nVERIFY: {problems} problem(s)")
sys.exit(1 if problems else 0)
