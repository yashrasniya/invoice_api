# SQLite → PostgreSQL migration plan (production server)

## What I found on the server (read-only inspection, nothing changed)

| Item | Finding |
|---|---|
| Host | `ubuntu@80.225.251.106` (Oracle, Ubuntu 22.04, **~1 GB RAM**, 36 GB disk free) |
| App | `/home/ubuntu/invoice_api/invoice_api`, gunicorn (3 workers, `127.0.0.1:8000`) behind nginx |
| Live DB | `/home/ubuntu/invoice_api/invoice_api/db.sqlite3` — 3.3 MB, 65 tables, ~19.8k rows, integrity `ok` |
| Stray DB | `/home/ubuntu/db.sqlite3` (Mar 2026, 22 tables) — old, not used by the app; do **not** migrate |
| Postgres | **PostgreSQL 14 already installed and running** (`postgresql@14-main`), only the default `postgres` DB exists — no app DB/role yet |
| Driver | `psycopg2-binary 2.9.11` already in the venv; Django 5.0 |
| Settings | `settings.py` hard-codes SQLite (`DATABASES`), same in local repo |
| Config | secrets in `invoice_api/invoice_api/.env`; some vars set in `gunicorn.service` |
| Backups | nightly cron `bin/backup_db.sh` 02:30 → `~/backup/nightly`; healthcheck cron every 2 min |
| Media | files live in `/var/www/invoice_media` — **not affected** by this migration |

The data is small, so a single short maintenance window (about 10–15 min) is enough. No need for live replication.

## Approach: Django `dumpdata` / `loaddata`

Chosen over `pgloader` because it goes through the ORM, so types (booleans, decimals, JSON, datetimes) are converted correctly, and it needs no extra tooling on a 1 GB box. Row counts are verified table-by-table afterwards.

## Local rehearsal — DONE (PostgreSQL 16, copy of the local dev DB)

Result: 9,475 objects loaded, **row counts match on all 44 data tables**, all id sequences ahead of max(id), `migrate --check` clean. Runs in ~15 s.

Code changes made (uncommitted, on the working tree):
- `invoice_api/invoice_api/settings.py` — `DB_*` env vars select PostgreSQL; unset = SQLite as before. Also an optional `SQLITE_PATH` to point at another SQLite file.
- `invoice_api/.env.example` — documents the `DB_*` vars.
- `invoice_api/accounts/api/views_invites.py` — `select_for_update(of=('self',))`. Real bug only Postgres exposes ("FOR UPDATE cannot be applied to the nullable side of an outer join"), it broke invite acceptance.
- `invoice_api/scripts/sqlite_to_postgres.sh` — the whole procedure, ending with a row-count comparison that fails on any mismatch.

Problems the rehearsal found (all handled in the script — they would have bitten the real cut-over):
1. **Migration `accounts.0009` fails on an empty Postgres** — it calls `cache.clear()`, the cache is a DB table that doesn't exist yet, and Postgres aborts the transaction. Fix: `createcachetable` *before* `migrate`.
2. **Data migrations pre-seed rows** (permissions, roles, plans) → duplicate-key errors on load. Fix: truncate the seeded tables after `migrate`, before `loaddata`.
3. **App signals fire during `loaddata`** (they ignore `raw=True`) and create audit logs / roles / Free subscriptions with clashing ids. Fix: detach model signals for the load only.
4. **Soft-deleted rows are invisible to `dumpdata`** (default manager) and invoices pointing at them break the FK check. Fix: `dumpdata --all`. Without it, deleted vendors/etc. would have been silently lost.

Test suite on Postgres: same 8 failures as on SQLite (pre-existing: aws/ocr/convertor/profile-upload tests), and the one Postgres-only failure above is fixed.

Not yet tested: real production data. The local DB is a dev copy; the server dry run (Phase 1) is what will show any data-specific problems (stricter typing, orphan FKs).

## Server dry run — DONE (2026-10-17)

Run on the server in a scratch copy (`~/pg_rehearsal/`), from a consistent snapshot of the live SQLite, into a throw-away database `invoice_rehearsal` (role `rehearsal_user`). The live app, its code, its SQLite file and gunicorn were not touched. `nice -n 15`, ~1m51s, RAM stayed ~380 MB used.

Result: **10,628 objects loaded, row counts match on every table, sequences OK**, ORM reads work on Postgres.

What it found (production-specific, none visible locally):
1. **Over-length values SQLite accepted** — Postgres rejects them:
   - `companies.Customers` pk=34 `gst_number` = "Test Company GST Number" (23 chars, column is 15). Junk test row.
   - `invoice.InvoiceExtractionLog` pk=46–50 `file` — 103-char paths in a 100-char column. Real file references.
   The script now has a preflight (`scripts/check_sqlite_data.py`) that lists all such values and stops. **Decision needed** before cut-over (see summary): fix pk=34 by hand; for the 5 file paths either widen `InvoiceExtractionLog.file` to `max_length=255` (needs a migration) or truncate them (breaks those 5 links).
   For the rehearsal both were shortened in the *snapshot copy only*.
2. **The server's migration files don't match its database.** The live DB has applied migrations that are not on disk on the server (accounts 0002/0003/0005, bill_share 0001, yaml_manager 0002/0003 …), and the repo's migration names differ from what production recorded for accounts, companies, inventory, invoice and whatsapp_integration. Most `migrations/` folders are untracked in git (bill_share, adminconfig, yaml_manager are not tracked at all), and the server has locally-modified `0001_initial` files.
   Consequence: on a fresh Postgres, `migrate` from the server's files does not create `bill_share_billshare` (that app has no migration files there). The script now runs `migrate --run-syncdb` as a second pass, which builds those tables from the models.
   **Do not run `migrate` on the live SQLite after deploying the repo's migrations as-is** — the histories diverge and Django would try to re-apply them.

## Phase 0 — Prepare (no downtime)

1. **Code change** (local, on a branch):
   - `settings.py`: read DB config from env; default to SQLite so local dev keeps working.
     ```python
     if os.environ.get("DB_NAME"):
         DATABASES = {"default": {
             "ENGINE": "django.db.backends.postgresql",
             "NAME": os.environ["DB_NAME"], "USER": os.environ["DB_USER"],
             "PASSWORD": os.environ["DB_PASSWORD"],
             "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
             "PORT": os.environ.get("DB_PORT", "5432"),
             "CONN_MAX_AGE": 60,
         }}
     else:  # existing sqlite config
     ```
   - `requirements.txt`: ensure `psycopg2-binary` is listed.
   - `.env.example`: document `DB_*` vars.
2. **Rehearse locally first**: install Postgres locally (or Docker), run the full procedure below against a copy of `db.sqlite3`, and fix any failures. Also run the test suite against Postgres.
3. **Create the DB and role on the server** (fresh, empty):
   ```sql
   CREATE ROLE invoice_user LOGIN PASSWORD '<strong, generated>';
   CREATE DATABASE invoice_db OWNER invoice_user ENCODING 'UTF8';
   ```
   Keep Postgres bound to localhost only (`listen_addresses = 'localhost'`, the default) — no public port.
4. Add the `DB_*` vars to the server `.env` **but don't restart yet**. Don't commit the password.
5. Postgres on 1 GB RAM: leave defaults (`shared_buffers` ~128 MB) — fine for this size; check `free -h` after.

## Phase 1 — Dry run on the server (no downtime, against a *copy*)

1. `cp db.sqlite3 /tmp/db_copy.sqlite3` and run the dump/load steps below pointing at `invoice_db_rehearsal` (a throw-away DB). Time it and confirm counts match. Drop the rehearsal DB afterwards.
2. This catches environment-specific problems (e.g. old rows violating constraints) before the real window.

## Phase 2 — Cut-over (maintenance window ~10–15 min)

1. `sudo systemctl stop gunicorn` (stops writes; nginx serves 502 briefly). Pause any cron/worker that writes to the DB.
2. **Backup**: `cp db.sqlite3 ~/backup/db.sqlite3.pre_postgres.<timestamp>` and `sqlite3 ... "PRAGMA integrity_check"`.
3. **Dump from SQLite** (settings still pointing at SQLite):
   ```bash
   cd ~/invoice_api/invoice_api && source ../venv/bin/activate
   python manage.py dumpdata --natural-foreign --natural-primary \
       --exclude contenttypes --exclude auth.permission \
       --exclude admin.logentry --exclude sessions.session \
       --indent 1 -o ~/backup/data_dump.json
   ```
   (Excluded tables are regenerated by `migrate`; sessions just force a re-login — see "Decisions" below.)
4. **Switch config to Postgres** (`DB_*` vars in `.env`), then build the schema:
   ```bash
   python manage.py migrate        # creates all tables from migrations on empty Postgres
   ```
5. **Load**:
   ```bash
   python manage.py loaddata ~/backup/data_dump.json
   ```
   If FK ordering errors appear, run the load inside one transaction with constraints deferred (Postgres defers FK checks to commit with Django's `loaddata`, so this normally just works).
6. **Reset sequences** (critical — otherwise the next insert collides with an existing id):
   ```bash
   python manage.py sqlsequencereset accounts companies invoice inventory billing \
       bill_share adminconfig yaml_manager ... | psql "$DATABASE_URL"
   ```
   (Generate the list from `INSTALLED_APPS`; I'll script this.)
7. **Verify** before opening traffic:
   - Row counts per table: SQLite vs Postgres (script compares all 65 tables; any difference = stop and roll back).
   - `python manage.py check` and `python manage.py migrate --check`.
   - Spot-check: a few invoices' totals, user logins, subscription/billing records, `Decimal` fields, JSON/yaml fields.
8. `sudo systemctl start gunicorn`; smoke test via the public URL: login, list invoices, create an invoice (confirms sequences), PDF export, Razorpay webhook path, mobile app login.

## Rollback

Any time before Phase 3: stop gunicorn, remove/unset `DB_*` in `.env`, start gunicorn → back on the untouched SQLite file (it is only read during the migration). If problems appear **after** go-live with new writes in Postgres, you'd lose those writes by reverting, so keep the observation window short and decide quickly; the Postgres data can be dumped back with `dumpdata` if needed.

## Phase 3 — After go-live

1. Watch `journalctl -u gunicorn -f` and the healthcheck for a day.
2. Update `~/bin/backup_db.sh` (currently copies the SQLite file) to run `pg_dump -Fc invoice_db` nightly into `~/backup/nightly`, with retention; **test a restore** once.
3. Update `deploy_backend.sh` / `DEPLOYMENT.md` and the local `dev.sh` docs for the new env vars.
4. Keep the SQLite file archived for ~2 weeks, then delete.
5. Optional: set `CONN_MAX_AGE`, add a `pg_stat` check to the healthcheck.

## Risks & things to check

- **1 GB RAM**: 3 gunicorn workers + Postgres is OK for this data size, but watch swap during `loaddata`.
- **Sequences** not reset → duplicate-key errors on first insert (step 6 covers it).
- **Case/collation differences**: SQLite `LIKE` is case-insensitive for ASCII; Postgres `LIKE` is not. Django's `icontains` is fine, but any raw SQL or `contains` search relied on this — grep for `raw(`, `.extra(`, `cursor.execute`.
- **Stricter typing**: SQLite tolerates wrong-typed values (e.g. strings in numeric columns, over-length strings); Postgres will reject them at load. The dry run in Phase 1 finds these.
- **Unique/NOT NULL violations** hidden in old data — same dry run.
- **Migrations folders are untracked in git** (`adminconfig/`, `bill_share/`, `yaml_manager/`, `billing/migrations/__init__.py` show as `??` locally). Make sure the server's migration files match the repo before the dry run, or `migrate` on empty Postgres may build a different schema than production SQLite.
- Server `.env` contains secrets and `gunicorn.service` has some env inline; add DB creds to `.env` only.

## Decisions I need from you

1. **Maintenance window**: OK to take the site down ~10–15 min (early morning, e.g. 03:00 IST after the 02:30 backup)?
2. **Sessions / admin log**: fine to drop (users re-login once)? Default: yes.
3. **Should I do the local code changes + local rehearsal first** (safe, no server changes), then the server dry run, and only run the real cut-over when you say go?

Nothing on the server has been modified so far.
