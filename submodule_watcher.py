"""Campus revision watcher — polls campus state for new master/asset revisions.

Watches campus's own state files (octo_cache.json + config.yaml) for changes
caused by an external campus invocation (e.g. gkms-texture-tools cronjob
calling `campus -ab --webab`, or a separate `campus -db` cron). When campus
publishes a new revision, this watcher triggers run.sh.

Two signals are tracked:
  - octoCacheRevision (asset bundles) — bumped by `campus -ab`
  - masterVersion (master database)    — bumped by `campus -db`

When either changes, run.sh is started in the background (subject to flock).

Configurable via environment:
  POLL_INTERVAL  seconds between checks (default: 600 = 10 minutes)
  CAMPUS_DIR     campus checkout location (default: /root/worker/campus)
"""

from __future__ import annotations

import datetime
import fcntl
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 600))
WORKDIR = Path(__file__).resolve().parent
CAMPUS_DIR = Path(os.environ.get("CAMPUS_DIR", "/root/worker/campus"))
LOCKFILE = Path("/tmp/gakutoolkit.lock")
WATCHER_LOCK = Path("/tmp/gakutoolkit-watcher.lock")
STATEFILE = WORKDIR / "res" / ".manifest" / "watcher_state.json"
LOGFILE = WORKDIR / "watcher.log"

OCTO_CACHE = CAMPUS_DIR / "cache" / "octo_cache.json"
CAMPUS_CONFIG = CAMPUS_DIR / "config.yaml"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGFILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watcher")

# ---------------------------------------------------------------------------
# Campus state probes
# ---------------------------------------------------------------------------


def _read_octo_revision() -> Optional[int]:
    """Return octo_cache.json's `revision` field, or None if unavailable."""
    if not OCTO_CACHE.exists():
        return None
    try:
        import json
        return int(json.loads(OCTO_CACHE.read_text()).get("revision", -1))
    except Exception as e:
        log.warning(f"Failed to read {OCTO_CACHE}: {e}")
        return None


def _read_master_version() -> Optional[str]:
    """Return config.yaml's `masterVersion` field, or None if unavailable."""
    if not CAMPUS_CONFIG.exists():
        return None
    try:
        for line in CAMPUS_CONFIG.read_text().splitlines():
            line = line.strip()
            if line.startswith("masterVersion:"):
                return line.split(":", 1)[1].strip()
    except Exception as e:
        log.warning(f"Failed to read {CAMPUS_CONFIG}: {e}")
    return None


def _current_state() -> Dict[str, object]:
    return {
        "octoCacheRevision": _read_octo_revision(),
        "masterVersion": _read_master_version(),
    }


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def _load_state() -> Dict[str, object]:
    if not STATEFILE.exists():
        return {}
    try:
        import json
        return json.loads(STATEFILE.read_text())
    except Exception as e:
        log.warning(f"Corrupt state file ({e}) — starting fresh")
        return {}


def _save_state(state: Dict[str, object]) -> None:
    import json
    STATEFILE.parent.mkdir(parents=True, exist_ok=True)
    STATEFILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def _is_running() -> bool:
    """Check if run.sh is already running via PID in lock file."""
    if not LOCKFILE.exists():
        return False
    try:
        content = LOCKFILE.read_text().strip()
        if content.isdigit():
            os.kill(int(content), 0)
            return True
        return True
    except (ProcessLookupError, ValueError):
        log.warning("Stale lock file found, removing")
        LOCKFILE.unlink(missing_ok=True)
        return False


def _trigger_run(changed: list[str]) -> None:
    if _is_running():
        log.info(f"Skipped: already running. Changed: {changed}")
        return

    log.info(f"Triggering run.sh — changed signals: {changed}")
    logfile = WORKDIR / f"output_watcher_{datetime.datetime.now():%Y%m%d_%H%M}.log"
    subprocess.Popen(
        ["bash", "run.sh"],
        cwd=str(WORKDIR),
        stdout=open(logfile, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.info(f"run.sh started, log={logfile.name}")


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------


def check_and_trigger() -> None:
    saved = _load_state()
    current = _current_state()

    if any(v is None for v in current.values()):
        log.warning(f"Incomplete campus state {current} — skipping this tick")
        return

    changed = [k for k in current if saved.get(k) != current[k]]
    _save_state(current)

    if not saved:
        log.info(f"First run — saved initial state: {current}")
        return

    if changed:
        for k in changed:
            log.info(f"  {k}: {saved.get(k)} → {current[k]}")
        _trigger_run(changed)
    else:
        log.debug(f"No changes (state: {current})")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _acquire_singleton() -> "object":
    """Acquire a process-wide flock so only one watcher runs per host.

    Returns the open file handle; caller must keep the reference for the
    lifetime of the process (closing it releases the lock). On contention,
    exits with code 1 rather than silently double-polling.
    """
    fh = WATCHER_LOCK.open("w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        try:
            holder = WATCHER_LOCK.read_text().strip()
        except Exception:
            holder = "?"
        log.error(f"Another watcher is already running (PID {holder}, lock {WATCHER_LOCK})")
        sys.exit(1)
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh


if __name__ == "__main__":
    _LOCK_HANDLE = _acquire_singleton()  # kept open for the process lifetime

    log.info(f"Starting campus watcher (interval={POLL_INTERVAL}s, pid={os.getpid()})")
    log.info(f"Watching campus state at {CAMPUS_DIR}")

    while True:
        try:
            check_and_trigger()
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
        time.sleep(POLL_INTERVAL)
