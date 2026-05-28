"""Submodule update watcher — polls GitHub for new commits and triggers run.sh.

Checks remote HEAD of adv and masterdb submodules every POLL_INTERVAL seconds.
If a new commit is detected, runs run.sh (with lock file check to prevent duplicates).

Usage:
  python3 submodule_watcher.py           # foreground
  systemctl start gakutoolkit-watcher    # systemd

Config via environment variables:
  POLL_INTERVAL  - seconds between checks (default: 600 = 10 minutes)
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 600))
WORKDIR = Path(__file__).resolve().parent
LOCKFILE = Path("/tmp/gakutoolkit.lock")
HASHFILE = WORKDIR / ".submodule_hashes"
LOGFILE = WORKDIR / "watcher.log"

SUBMODULES = {
    "adv": {
        "api_url": "https://api.github.com/repos/DreamGallery/Campus-adv-txts/commits/main",
        "local_path": WORKDIR / "res" / "adv",
    },
    "masterdb": {
        "api_url": "https://api.github.com/repos/pinisok/gakumas-master-translation/commits/main",
        "local_path": WORKDIR / "res" / "masterdb",
    },
}

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
# Functions
# ---------------------------------------------------------------------------


def _load_saved_hashes() -> dict:
    """Load previously saved commit hashes."""
    hashes = {}
    if HASHFILE.exists():
        for line in HASHFILE.read_text().strip().splitlines():
            parts = line.split("=", 1)
            if len(parts) == 2:
                hashes[parts[0]] = parts[1]
    return hashes


def _save_hashes(hashes: dict) -> None:
    """Save current commit hashes."""
    content = "\n".join(f"{k}={v}" for k, v in sorted(hashes.items()))
    HASHFILE.write_text(content + "\n")


def _get_remote_hash(api_url: str) -> str | None:
    """Fetch latest commit SHA from GitHub API."""
    try:
        import urllib.request
        import json

        req = urllib.request.Request(api_url)
        req.add_header("User-Agent", "GakuToolkit-Watcher")
        req.add_header("Accept", "application/vnd.github.v3+json")

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("sha", "")
    except Exception as e:
        log.error(f"Failed to fetch {api_url}: {e}")
        return None


def _is_running() -> bool:
    """Check if run.sh is already running via lock file."""
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
    """Trigger run.sh in the background."""
    if _is_running():
        log.info(f"Skipped: already running. Changed: {changed}")
        return

    log.info(f"Triggering run.sh — changed submodules: {changed}")
    import datetime

    logfile = WORKDIR / f"output_watcher_{datetime.datetime.now():%Y%m%d_%H%M}.log"

    subprocess.Popen(
        ["bash", "run.sh"],
        cwd=str(WORKDIR),
        stdout=open(logfile, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.info(f"run.sh started, log={logfile.name}")


def check_and_trigger() -> None:
    """Check submodules for updates and trigger if changed."""
    saved = _load_saved_hashes()
    current = {}
    changed = []

    for name, info in SUBMODULES.items():
        remote_hash = _get_remote_hash(info["api_url"])
        if remote_hash is None:
            log.warning(f"Could not fetch {name}, skipping")
            current[name] = saved.get(name, "")
            continue

        current[name] = remote_hash
        prev = saved.get(name, "")

        if prev and prev != remote_hash:
            log.info(f"{name} updated: {prev[:8]} → {remote_hash[:8]}")
            changed.append(name)
        elif not prev:
            log.info(f"{name} initial hash: {remote_hash[:8]}")

    _save_hashes(current)

    if changed:
        _trigger_run(changed)
    else:
        log.debug("No changes detected")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(f"Starting submodule watcher (interval={POLL_INTERVAL}s)")
    log.info(f"Watching: {list(SUBMODULES.keys())}")

    # Initial hash save (don't trigger on first run)
    if not HASHFILE.exists():
        log.info("First run — saving initial hashes")
        hashes = {}
        for name, info in SUBMODULES.items():
            h = _get_remote_hash(info["api_url"])
            if h:
                hashes[name] = h
                log.info(f"  {name}: {h[:8]}")
        _save_hashes(hashes)

    while True:
        try:
            check_and_trigger()
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL)
