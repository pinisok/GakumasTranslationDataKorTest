#!/bin/bash
# campus-cron — single owner of /root/worker/campus invocations.
#
# Pulls the latest assetbundles + master DB so both consumers can read a
# consistent snapshot of /root/worker/campus/cache/:
#   - GakuToolkit/scripts/campus_sync.py  — reads cache/raw, cache/masterYaml
#   - gkms-texture-tools/cronjob.sh       — reads cache/assets
#
# Neither consumer invokes campus on its own anymore: see GakuToolkit/run.sh
# (uses `sync … --skip-campus`) and gkms-texture-tools/cronjob.sh
# (RUN_CAMPUS_FETCH=0 / CAMPUS_AUTO_UPDATE=0 by default). That avoids a race
# where one consumer downloads a new revision into cache/, the other's cleanup
# fires before it's processed, and the revision is silently lost.
#
# Crontab example (every 30 minutes):
#   */30 * * * * /root/worker/GakuToolkit/campus-cron.sh >> /var/log/campus-cron.log 2>&1
#
# Shared lock is the same /tmp/campus.lock that GakuToolkit campus_sync and
# gkms-texture-tools cronjob both honour, so any ad-hoc invocation also
# queues behind this one.
set -euo pipefail

CAMPUS_DIR="${CAMPUS_DIR:-/root/worker/campus}"
CAMPUS_LOCK="${CAMPUS_LOCK:-/tmp/campus.lock}"
CAMPUS_LOCK_TIMEOUT="${CAMPUS_LOCK_TIMEOUT:-1800}"
CAMPUS_FLAGS="${CAMPUS_FLAGS:--ab --webab -db}"
CAMPUS_AUTO_UPDATE="${CAMPUS_AUTO_UPDATE:-1}"
CAMPUS_BRANCH="${CAMPUS_BRANCH:-main}"

echo "[$(date '+%F %T')] campus-cron start"

# Self-update campus source (git pull only — `go run` recompiles on demand).
if [ "$CAMPUS_AUTO_UPDATE" = "1" ] && [ -d "$CAMPUS_DIR/.git" ]; then
  echo "  self-update (branch: $CAMPUS_BRANCH)"
  (
    cd "$CAMPUS_DIR"
    old=$(git rev-parse HEAD)
    git fetch --quiet origin "$CAMPUS_BRANCH"
    new=$(git rev-parse "origin/$CAMPUS_BRANCH")
    if [ "$old" != "$new" ]; then
      echo "  $old → $new (fast-forward)"
      git pull --ff-only --quiet origin "$CAMPUS_BRANCH"
      go mod download
    else
      echo "  already at $new"
    fi
  ) || echo "  ⚠ self-update failed — continuing with existing source"
fi

# Run campus under shared lock. Blocking with hard timeout so a hung
# ad-hoc holder cannot silently strand the cron.
(
  flock -w "$CAMPUS_LOCK_TIMEOUT" 9 || {
    echo "  ⚠ campus shared lock timed out after ${CAMPUS_LOCK_TIMEOUT}s"
    exit 1
  }
  echo "$$" >&9
  cd "$CAMPUS_DIR" && eval "env CGO_ENABLED=1 go run . $CAMPUS_FLAGS"
) 9>"$CAMPUS_LOCK"

echo "[$(date '+%F %T')] campus-cron done"
