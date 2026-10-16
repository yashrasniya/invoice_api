#!/usr/bin/env bash
#
# sqlite_to_postgres.sh — copy every row of the SQLite database into an EMPTY PostgreSQL database.
#
# Usage (run from invoice_api/ with the venv active):
#   SQLITE_PATH=/path/to/db.sqlite3 \
#   DB_NAME=... DB_USER=... DB_PASSWORD=... DB_HOST=127.0.0.1 DB_PORT=5432 \
#   PSQL="psql -h 127.0.0.1 -U invoice_user -d invoice_db" \
#   scripts/sqlite_to_postgres.sh
#
# SQLITE_PATH is only read, never written. The target database must exist and be empty.
# PSQL must be a command that opens a session on the target DB (same DB as DB_*).
#
# Steps: dump (SQLite) -> createcachetable + migrate (Postgres) -> truncate seeded rows
#        -> loaddata -> reset sequences -> compare row counts for every table.
set -euo pipefail

: "${SQLITE_PATH:?set SQLITE_PATH}" "${DB_NAME:?set DB_NAME}" "${PSQL:?set PSQL}"
PYTHON="${PYTHON:-python}"
DUMP="${DUMP:-$(mktemp -t sqlite_dump.XXXXXX.json)}"
CACHE_TABLE="django_cache"   # CACHES['default']['LOCATION'] in settings.py

say() { printf '\n==> %s\n' "$*"; }

say "1/6 Dump from SQLite ($SQLITE_PATH) -> $DUMP"
(unset DB_NAME
 "$PYTHON" manage.py dumpdata --all --natural-foreign --natural-primary \
   --exclude contenttypes --exclude auth.permission \
   --exclude admin.logentry --exclude sessions.session \
   --indent 1 -o "$DUMP" 2> >(grep -viE "W0|HINT|^\?:|fields.W" >&2))

say "1b/6 Preflight: values PostgreSQL would reject (SQLite ignores varchar length)"
(unset DB_NAME; PYTHONPATH=. DUMP="$DUMP" "$PYTHON" scripts/check_sqlite_data.py 2> >(grep -viE "W0|HINT|^\?:|fields.W" >&2)) \
  || { echo "Fix the rows above in SQLite (or the dump), then re-run."; exit 1; }

say "2/6 Create the cache table, then run migrations on PostgreSQL"
# The cache table must exist first: migration accounts.0009 calls cache.clear(), and on
# PostgreSQL a failed query inside a migration aborts the whole transaction.
"$PYTHON" manage.py createcachetable 2>&1 | grep -v "^\s*$" || true
"$PYTHON" manage.py migrate --noinput 2>&1 | tail -3
# Apps without migration files (e.g. bill_share on the server) get their tables from the models.
# Needs a second pass so the tables they reference (accounts_user, ...) already exist.
"$PYTHON" manage.py migrate --noinput --run-syncdb 2>&1 | tail -2

say "3/6 Remove rows that data migrations seeded (the dump contains the real ones)"
TABLES=$($PSQL -At -c "select string_agg(quote_ident(tablename), ', ') from pg_tables
  where schemaname='public'
  and tablename not in ('django_migrations','django_content_type','auth_permission','$CACHE_TABLE')")
$PSQL -q -c "truncate $TABLES restart identity cascade"

say "4/6 Load data"
# App signals (accounts/signals.py) ignore raw=True and would create audit rows, roles and Free
# subscriptions that collide with the dumped ones, so detach model signals for this load only.
DUMP="$DUMP" "$PYTHON" - <<'PYEOF'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "invoice_api.settings")
django.setup()
from django.core.management import call_command
from django.db.models import signals
for sig in (signals.pre_save, signals.post_save, signals.pre_delete, signals.post_delete, signals.m2m_changed):
    sig.receivers = []
    sig.sender_receivers_cache.clear()
call_command("loaddata", os.environ["DUMP"])
PYEOF

say "5/6 Reset id sequences"
APPS=$("$PYTHON" - <<'EOF'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "invoice_api.settings")
django.setup()
from django.apps import apps
print(" ".join(c.label for c in apps.get_app_configs()))
EOF
)
"$PYTHON" manage.py sqlsequencereset $APPS 2>/dev/null | $PSQL -q -At >/dev/null

say "6/6 Compare row counts (SQLite vs PostgreSQL)"
SQLITE_PATH="$SQLITE_PATH" PSQL="$PSQL" "$PYTHON" - <<'EOF'
import os, sqlite3, subprocess, sys
src = sqlite3.connect(f"file:{os.environ['SQLITE_PATH']}?mode=ro", uri=True)
skip = {"django_migrations", "django_content_type", "auth_permission", "django_admin_log",
        "django_session", "django_cache"}
bad = 0
for (t,) in src.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1"):
    if t in skip:
        continue
    a = src.execute(f'select count(*) from "{t}"').fetchone()[0]
    out = subprocess.run(os.environ["PSQL"].split() + ["-At", "-c", f'select count(*) from "{t}"'],
                         capture_output=True, text=True)
    b = int(out.stdout.strip()) if out.returncode == 0 else -1
    if a != b:
        bad += 1
        print(f"MISMATCH {t}: sqlite={a} postgres={b}")
print("ALL TABLE COUNTS MATCH" if not bad else f"{bad} table(s) differ")
sys.exit(1 if bad else 0)
EOF
