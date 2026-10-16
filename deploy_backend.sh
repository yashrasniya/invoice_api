#!/bin/bash
# Deploy the Django backend to production. See DEPLOYMENT.md.
#
#   ./deploy_backend.sh             pull + restart (stops before restarting if there are unapplied migrations)
#   ./deploy_backend.sh --migrate   also apply the committed, pending migrations (never generates any)
#
# Steps: check local code is pushed -> DB backup -> git pull -> pip install (if requirements changed)
#        -> migration check -> restart gunicorn -> health check.
# Env overrides: SSH_KEY, HOST, BRANCH
set -euo pipefail

SSH_KEY="${SSH_KEY:-$HOME/.ssh/ssh-key-2026-03-03.key}"
HOST="${HOST:-ubuntu@80.225.251.106}"
BRANCH="${BRANCH:-feature/subscription-authz}"
SITE="https://invoice.orvine.in"
MIGRATE=0

case "${1:-}" in
  "") ;;
  --migrate) MIGRATE=1 ;;
  -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
  *) echo "Unknown option: $1 (try --help)" >&2; exit 1 ;;
esac

cd "$(dirname "$0")"

# 1. Local code must be committed and pushed, otherwise the server will not get it.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Uncommitted changes to tracked files. Commit and push first:"; git status --short --untracked-files=no; exit 1
fi
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git ls-remote origin "refs/heads/$BRANCH" | cut -f1)
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "Local HEAD ($LOCAL) is not what origin/$BRANCH has (${REMOTE:-none}). Push first (or switch branch)."; exit 1
fi
echo "Deploying $(git log --oneline -1) to $HOST"

# 2. Remote steps
ssh -i "$SSH_KEY" "$HOST" "MIGRATE=$MIGRATE BRANCH=$BRANCH bash -s" <<'REMOTE'
set -euo pipefail
cd ~/invoice_api

echo "== DB backup"
~/bin/backup_db.sh
ls -1t ~/backup/nightly | head -1

PREV=$(git rev-parse HEAD)
echo "== git pull (previous commit: $PREV)"
git pull --ff-only
NEW=$(git rev-parse HEAD)

if git diff --name-only "$PREV" "$NEW" | grep -q '^requirements.txt$'; then
  echo "== requirements.txt changed: pip install"
  ./venv/bin/pip install -q -r requirements.txt
fi

cd invoice_api
source ../venv/bin/activate
export PYTHONWARNINGS=ignore

echo "== migration check"
if python manage.py makemigrations --check --dry-run >/tmp/pending_migrations.txt 2>&1; then
  echo "no pending model changes"
else
  grep -E "^Migrations for|^  [a-z_]+/migrations|^    - " /tmp/pending_migrations.txt || cat /tmp/pending_migrations.txt
  echo
  echo "The models have changes with no migration in git. Do NOT run makemigrations on the server."
  echo "Create and commit the migration locally, push, then deploy again."
  echo "Code is pulled but gunicorn was NOT restarted. (rollback point: git checkout $PREV)"
  exit 2
fi

if [ "$MIGRATE" = "1" ]; then
  echo "== migrate plan"
  python manage.py migrate --plan | grep -vE "^\?|WARN|HINT|SECURITY|^\s*$" || true
  python manage.py migrate
else
  if python manage.py showmigrations 2>/dev/null | grep -q '\[ \]'; then
    echo "There are unapplied migrations. Re-run with --migrate."; exit 2
  fi
fi

echo "== restart gunicorn"
sudo systemctl restart gunicorn.service
sleep 4
systemctl is-active gunicorn.service
echo "$PREV" > ~/last_deployed_from_commit
REMOTE

# 3. Health check from outside
echo "== health check"
for i in 1 2 3 4 5; do
  CODE=$(curl -s -o /dev/null -m 15 -w "%{http_code}" "$SITE/api/" || true)
  [ "$CODE" = "200" ] && { echo "$SITE/api/ -> 200 OK"; echo "Deploy finished."; exit 0; }
  echo "attempt $i: $CODE"; sleep 3
done
echo "Health check FAILED. Check: ssh in, 'sudo journalctl -u gunicorn.service -n 50'. Rollback: see DEPLOYMENT.md section 3.4." >&2
exit 1
