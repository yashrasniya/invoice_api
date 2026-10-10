# Production Deployment Guide

Everything needed to deploy, operate and recover the Invoice Orvine production server.
**No secrets are stored in this file.** Credentials live only in the server's `.env` (see [Configuration](#configuration)).

- Site: https://invoice.orvine.in (frontend at `/app/`, API at `/api/`, Django admin at `/admin/`)
- Server: Ubuntu 22.04, `ubuntu@80.225.251.106` (SSH key auth only; ask the owner for the key)
- Quick login: `./login.sh` from the repo root

---

## 1. Architecture

```
Browser ──HTTPS──> nginx (443)
                    ├─ /app/*      -> static React build   (/var/www/bill_soft)
                    ├─ /          -> landing page          (/var/www/landing_page)
                    ├─ /static/   -> Django static         (/var/www/invoice_static)
                    ├─ /media/    -> uploaded files        (/var/www/invoice_media)
                    └─ /api/, /admin/ -> gunicorn 127.0.0.1:8000 (Django)
                                          └─ SQLite DB
FastAPI service (uvicorn, :8001) = invoice_convertor_pipeline (called by Django internally)
```

| Piece | Location on server | Managed by |
|---|---|---|
| Django backend (git checkout) | `~/invoice_api` (app in `~/invoice_api/invoice_api`) | `gunicorn.service` |
| Python venv | `~/invoice_api/venv` | - |
| Database (SQLite) | `~/invoice_api/invoice_api/db.sqlite3` | - |
| Frontend upload dir | `~/build` -> rsynced to `/var/www/bill_soft` | `deploy_F.sh` |
| PDF/OCR pipeline | `~/invoice_convertor_pipeline` | `fastapi.service` |
| Web server | `/etc/nginx/sites-available/bill_soft` | `nginx.service` |
| TLS certs | `/etc/letsencrypt` | certbot (auto-renew) |

Backend deploys from git branch **`feature/subscription-authz`** (the server tracks `origin/feature/subscription-authz`).

---

## 2. Deploying the frontend

Source: `bill_makeing_sof/`. From that folder on your machine:

```bash
bash deploy.sh
```

What it does: builds with `VITE_APP_URL=/api npm run build`, copies `build/` to `~/build` on the server (scp), then runs `deploy_F.sh` there, which rsyncs it into `/var/www/bill_soft`. No restart needed; the build is static.

Verify: open https://invoice.orvine.in/app/login/ and hard-refresh.

---

## 3. Deploying the backend

### 3.1 Before you start
1. Commit and push your changes to `feature/subscription-authz`.
2. Make sure everything the code imports is **committed**, not just present locally (a missing file crashes gunicorn on start).
3. **Migrations are git-ignored** (`.gitignore`: `**/migrations/*.py`, only each app's `0001_initial.py` is tracked), so local and server migration histories differ. See [3.3](#33-migrations-important).

### 3.2 Deploy steps

**Scripted (recommended):** from the repo root on your machine

```bash
./deploy_backend.sh             # backup, pull, restart, health check
./deploy_backend.sh --migrate   # same, plus generate + apply pending migrations on the server
```

It refuses to run if tracked files are uncommitted or HEAD is not pushed, backs up the DB first, runs `pip install`
only when `requirements.txt` changed, and **stops before restarting** if models need migrations (re-run with `--migrate`
after reviewing what it printed). It finishes with an external health check of `/api/`. Override defaults with
`SSH_KEY`, `HOST`, `BRANCH` env vars.

**Manual equivalent:**

```bash
./login.sh                      # SSH in
cd ~/invoice_api && git pull

# ONLY if models changed, back up first (see 3.3), then:
cd invoice_api && source ../venv/bin/activate
python manage.py makemigrations --check --dry-run   # shows what is pending
python manage.py makemigrations <app> ...           # generate on the server
python manage.py migrate

sudo systemctl restart gunicorn.service
```

Verify:
```bash
systemctl is-active gunicorn nginx
curl -s -o /dev/null -w "%{http_code}\n" https://invoice.orvine.in/api/    # expect 200
sudo journalctl -u gunicorn.service -n 30 --no-pager                        # no tracebacks
```

### 3.3 Migrations (important)
- The server's migration files are **its own** (generated there). Never copy local migration files to the server: numbering and dependencies differ and `migrate` will fail or desync.
- When a model changes, run `makemigrations` **on the server** after `git pull`, read the generated file, then `migrate`.
- **Always back up the DB before any `migrate`:**
  ```bash
  ~/bin/backup_db.sh && ls -la ~/backup/nightly | tail -3
  ```
  This writes an integrity-checked, gzipped copy to `~/backup/nightly/`. Do not use a plain `cp` of the live SQLite file.
- Prefer additive migrations (new tables/nullable columns). Destructive ones need a restore plan first.

### 3.4 Rollback
- **Code:** `cd ~/invoice_api && git log --oneline`, then `git checkout <good-commit>` (or `git revert`) and restart gunicorn.
- **Database:** stop gunicorn, restore a backup, start it:
  ```bash
  sudo systemctl stop gunicorn.service
  gunzip -c ~/backup/nightly/db_YYYYMMDD_HHMM.sqlite3.gz > /tmp/restore.sqlite3
  cp /tmp/restore.sqlite3 ~/invoice_api/invoice_api/db.sqlite3
  sudo systemctl start gunicorn.service
  ```
- **nginx / gunicorn config:** timestamped copies of earlier versions are in `~/backup/` (`nginx_bill_soft.pre_*`, `gunicorn.service.pre_*`).

---

## 4. Configuration

Secrets are read from `~/invoice_api/invoice_api/.env` (mode `600`, git-ignored, loaded by `settings.py`).
Non-secret service settings live in `/etc/systemd/system/gunicorn.service`. After editing either, restart gunicorn
(`sudo systemctl daemon-reload` first if the unit file changed).

| Variable | Where | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | `.env` | Signs sessions and JWTs. Rotating it logs everyone out once. **Back it up.** |
| `EMAIL_USER`, `EMAIL_PASS` | `.env` | Gmail account used for app email **and** monitoring alerts |
| `key_id`, `key_secret` | `.env` | Razorpay (live) |
| `ACCESS_TOKEN`, `PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID` | `.env` | WhatsApp Business API |
| `DJANGO_HSTS_SECONDS` | `.env` (optional) | HSTS max-age; default 86400. Raise to `31536000` once confirmed stable |
| `DJANGO_SSL_REDIRECT` | `.env` (optional) | Off by default; nginx already redirects HTTP to HTTPS |
| `DJANGO_ALLOWED_HOSTS` | `.env` (optional) | Overrides allowed hosts |
| `STATIC_ROOT`, `MEDIA_ROOT`, `INVOICE_CONVERTOR_PIPLINE_URL`, `GOOGLE_OAUTH_CLIENT_ID`, `FRONTEND_URL` | gunicorn unit | Paths / public config |

Never paste credential values into chat, tickets or commits. If a secret was exposed, rotate it at the provider.

---

## 5. Server configuration notes

**gunicorn** (`gunicorn.service`): 3 workers, `--timeout 120`, `--max-requests 500` (+ jitter 50, recycles workers to bound memory), bound to `127.0.0.1:8000`, `Restart=always`, logs to journald.

**nginx** (`/etc/nginx/sites-available/bill_soft`):
- HTTP is redirected to HTTPS; certificates are managed by certbot.
- `/api/` and `/admin/` proxy to gunicorn with `Host`, `X-Real-IP`, `X-Forwarded-Proto $scheme` and `X-Forwarded-For $remote_addr`.
  Django needs these: the forwarded-proto header lets it treat requests as HTTPS (secure cookies, HSTS), and the real client IP is what the DRF anonymous throttle (5/min) keys on. **Do not remove them**, or all anonymous users share one throttle bucket.
- `proxy_read_timeout`/`proxy_send_timeout` on `/api/` are 120s to match gunicorn's timeout. Keep them in sync.
- `client_max_body_size 100M`, `server_tokens off`, security headers on frontend pages via `/etc/nginx/snippets/security_headers.conf`.
- Maintenance mode: `sudo touch /etc/nginx/maintenance.flag` serves the maintenance page; `sudo rm` it to go live again.
- Always test before reloading: `sudo nginx -t && sudo systemctl reload nginx`.

**Swap:** 2 GB `/swapfile` (swappiness 10). The box has under 1 GB RAM, so avoid adding workers without adding memory.

---

## 6. Backups

| What | How | Where |
|---|---|---|
| Database | `~/bin/backup_db.sh`, cron daily 02:30. Consistent SQLite `.backup`, integrity-checked, gzipped, 14 days kept | `~/backup/nightly/` (log: `backup.log`) |
| Manual / pre-change copies | by hand | `~/backup/` |

**Gap:** backups are on the same server. Copy them off-machine (S3, another host) to survive a disk loss.
Uploaded files (`/var/www/invoice_media`) are not backed up yet.

---

## 7. Monitoring and alerts

- `~/bin/healthcheck.sh` runs every 2 minutes (cron). It checks gunicorn directly and the site through nginx.
- After 3 consecutive API failures it restarts gunicorn automatically. State and history: `~/monitor/`, log `~/monitor/healthcheck.log` (empty = healthy).
- **Email alerts** (sent via `~/bin/send_alert.py`, subject prefix `[invoice-prod]`) for: site DOWN (2 failures in a row), gunicorn auto-restart, RECOVERED, disk >= 85%, available memory < 80 MB, a service not running (warnings repeat at most every 6 h), and a failed nightly backup.
- Limitation: the monitor runs on the server itself, so a full server outage cannot email. Add an external pinger (e.g. UptimeRobot) on `https://invoice.orvine.in/api/`.
- Cron entries: `crontab -l` as `ubuntu`.

**Logs**

| Log | Location | Rotation |
|---|---|---|
| gunicorn (access + errors) | `journalctl -u gunicorn.service` | journald capped at 500 MB / 30 days |
| Django app logs | `~/invoice_api/invoice_api/logs/*.log` | `/etc/logrotate.d/invoice_api` (daily or 10 MB, 8 kept, gzip) |
| nginx | `/var/log/nginx/` | default logrotate, 14 days |
| health check | `~/monitor/healthcheck.log` | grows slowly, only on events |

---

## 8. Troubleshooting

| Symptom | Check / fix |
|---|---|
| Site down / 502 | `systemctl status gunicorn`; `journalctl -u gunicorn -n 50`. Usually an import error from a file that was not committed, or a bad migration. Roll back (3.4). |
| Login returns 401 | A stale auth cookie from before a `SECRET_KEY` change. Public endpoints ignore it now; users just log in again. |
| Many `429` errors | The anonymous throttle (5/min per IP). Check nginx still sends `X-Forwarded-For`. |
| Worker timeouts / SIGKILL in the gunicorn log | Slow PDF/OCR request or out-of-memory. Check `free -m`, `swapon --show`, and the OOM lines in `journalctl -k`. |
| `DisallowedHost` / 400 on the raw IP | Expected. Use the domain; the IP is not in `ALLOWED_HOSTS`. |
| `SECURITY: DJANGO_SECRET_KEY is not set` in logs | `.env` is missing or unreadable. It must be at `~/invoice_api/invoice_api/.env`. |
| Migration error on `migrate` | Restore the pre-migrate backup if data changed, read the error, and fix by writing a corrective migration on the server (3.3). |
| TLS cert expiring | certbot renews automatically; check `sudo certbot certificates` and `sudo certbot renew --dry-run`. |

---

## 9. Known gaps / follow-ups

- Rotate credentials that were exposed in plain text earlier (WhatsApp token, Gmail app password, Razorpay live key), and keep them only in `.env`.
- Server migrations are out of step with git; consider committing a clean migration set.
- The database is SQLite on one server; moving to PostgreSQL (already installed on the box) is the next scalability step.
- Add off-server backups, media backups and an external uptime check.
- `/admin/` is publicly reachable; consider restricting it by IP.
