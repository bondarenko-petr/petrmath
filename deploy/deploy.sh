#!/bin/bash
# Run as petrmath. No DB migrations, data deletion or root shell execution.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
APP=/srv/petrmath/app
VENVS=/srv/petrmath/venvs
ACKS=/etc/petrmath-deploy/migrations
[[ $# == 1 && $1 =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA' >&2; exit 64; }
TARGET=$1
[[ $(id -un) == petrmath ]] || { echo 'Run as petrmath' >&2; exit 64; }
exec 9>/srv/petrmath/deploy.lock
flock -n 9 || { echo 'Another deployment is running' >&2; exit 75; }
cd "$APP"
[[ $(git remote get-url origin) == https://github.com/bondarenko-petr/petrmath.git ]] || { echo 'Unexpected Git remote' >&2; exit 1; }
[[ -z $(git status --porcelain --untracked-files=normal) ]] || { echo 'Server checkout contains local changes; resolve manually' >&2; exit 1; }
[[ -f .env && -x .venv/bin/python ]] || { echo 'Existing .env and virtualenv are required' >&2; exit 1; }
git fetch origin main
[[ $(git rev-parse origin/main) == "$TARGET" ]] || { echo 'Commit is no longer latest main; deploy the newest workflow run' >&2; exit 1; }
OLD=$(git rev-parse HEAD)
if [[ $OLD == "$TARGET" ]]; then
    /usr/bin/systemctl is-active --quiet petrmath.service
    curl --fail --silent --show-error https://prosto5.ru/api/health >/dev/null
    echo 'This commit is already deployed.'
    exit 0
fi
git merge-base --is-ancestor "$OLD" "$TARGET" || { echo 'Server history diverged from main' >&2; exit 1; }
# Never allow Git to replace persistent/private state.
[[ -z $(git ls-tree -r --name-only "$TARGET" -- .env .env.local data .venv) ]] || { echo 'Commit tracks private/runtime files; refusing deployment' >&2; exit 1; }
if [[ -n $(git diff --name-only "$OLD" "$TARGET" -- sql/) ]]; then
    [[ -f "$ACKS/$TARGET" && $(cat "$ACKS/$TARGET") == "$TARGET" ]] || {
        echo "SQL changed. Back up DB, review/apply compatible migrations manually, then root must acknowledge $TARGET. No code was changed." >&2
        exit 1
    }
fi
# Hold the application's cleanup lock until deployment has finished.
CLEANUP_DIR=$(.venv/bin/python - <<'PYCODE'
import os
from database import ROOT
print(os.environ.get('GOOGLE_DRIVE_PRIVATE_DIR', str(ROOT / 'data' / 'google-drive')))
PYCODE
)
mkdir -p -- "$CLEANUP_DIR"
exec 8>"$CLEANUP_DIR/cleanup.lock"
flock -n 8 || { echo 'Archive cleanup is running; retry later' >&2; exit 75; }
# Refuse before touching the running app when an archive job is active.
.venv/bin/python - <<'PY'
from accounts import database
with database() as (cursor, p):
    cursor.execute("SELECT COUNT(*) AS n FROM material_archives WHERE status IN ('building','uploading','verifying')")
    if cursor.fetchone()['n']:
        raise SystemExit('Archive jobs are active; retry when they finish.')
PY
mkdir -p "$VENVS"
NEW_ENV="$VENVS/$TARGET"
# A new environment never modifies the environment of the running release.
if [[ -e "$NEW_ENV" ]]; then
    echo 'A previous attempt left a virtualenv. Review/remove it manually before retrying.' >&2
    exit 1
fi
python3 -m venv "$NEW_ENV"
REQ=$(mktemp /srv/petrmath/deploy-requirements.XXXXXX)
trap 'rm -f "$REQ"' EXIT
git show "$TARGET:requirements.txt" > "$REQ"
"$NEW_ENV/bin/python" -m pip install --disable-pip-version-check -r "$REQ"
"$NEW_ENV/bin/python" -m pip check
# Check persistent DB connectivity again before downtime; health alone is not a DB check.
.venv/bin/python - <<'PY'
from accounts import database
with database() as (cursor, p):
    cursor.execute('SELECT COUNT(*) AS n FROM users')
    cursor.fetchone()
PY
OLD_ENV=$(readlink -f .venv)
if [[ ! -L .venv ]]; then
    # Keep the original environment for rollback. Entry-point scripts contain
    # absolute paths, so this service/deployer always uses python -m instead.
    LEGACY="$APP/.venv-before-auto-deploy"
    [[ ! -e "$LEGACY" ]] || { echo 'Legacy environment backup already exists' >&2; exit 1; }
fi
CHANGED=0
rollback() {
    rc=$?
    (( rc != 0 )) || rc=1
    trap - ERR HUP INT TERM
    if (( CHANGED )); then
        echo "Deployment failed; restoring code $OLD and previous environment" >&2
        git checkout --detach "$OLD" || true
        if [[ -L "$APP/.venv" ]]; then
            rm "$APP/.venv"
            ln -s "$OLD_ENV" "$APP/.venv"
        elif [[ ! -e "$APP/.venv" ]]; then
            ln -s "$OLD_ENV" "$APP/.venv"
        fi
        sudo -n /usr/bin/systemctl restart petrmath.service || true
        curl --fail --silent --show-error --retry 5 --retry-connrefused --retry-delay 2 http://127.0.0.1:8000/api/health || true
    fi
    exit "${rc:-1}"
}
trap rollback ERR HUP INT TERM
# Recheck after dependency installation; do not interrupt archive creation.
.venv/bin/python - <<'PY'
from accounts import database
with database() as (cursor, p):
    cursor.execute("SELECT COUNT(*) AS n FROM material_archives WHERE status IN ('building','uploading','verifying')")
    if cursor.fetchone()['n']:
        raise SystemExit('Archive jobs started during preparation; retry later.')
PY
# Graceful stop waits for FastAPI background response tasks; do not start an
# archive or maintenance operation while a deployment is being scheduled.
sudo -n /usr/bin/systemctl stop petrmath.service
CHANGED=1
if [[ ! -L .venv ]]; then
    OLD_ENV="$LEGACY"
    mv .venv "$LEGACY"
else
    rm .venv
fi
ln -s "$NEW_ENV" .venv
git checkout --detach "$TARGET"
sudo -n /usr/bin/systemctl start petrmath.service
for attempt in $(seq 1 20); do
    if /usr/bin/systemctl is-active --quiet petrmath.service && curl --fail --silent http://127.0.0.1:8000/api/health >/dev/null; then
        break
    fi
    sleep 2
done
/usr/bin/systemctl is-active --quiet petrmath.service
curl --fail --silent --show-error http://127.0.0.1:8000/api/health >/dev/null
# Confirm the application, using its own .env, can query the production DB.
.venv/bin/python - <<'PY'
from accounts import database
with database() as (cursor, p):
    cursor.execute('SELECT COUNT(*) AS n FROM users')
    cursor.fetchone()
    cursor.execute('SELECT COUNT(*) AS n FROM lessons')
    cursor.fetchone()
PY
curl --fail --silent --show-error --retry 3 --retry-delay 2 https://prosto5.ru/api/health >/dev/null
trap - ERR HUP INT TERM
echo "Deployed $TARGET (previous $OLD). DB, .env and data files preserved."
