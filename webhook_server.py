"""GitHub Webhook server for auto-triggering GakuToolkit on submodule updates.

Listens for push events from:
  - DreamGallery/Campus-adv-txts (adv submodule)
  - pinisok/gakumas-master-translation (masterdb submodule)

On push to main branch, runs run.sh if not already running (lock file check).

Usage:
  python3 webhook_server.py                    # foreground
  nohup python3 webhook_server.py &            # background
  pm2 start webhook_server.py --interpreter python3  # pm2

Config via environment variables:
  WEBHOOK_PORT    - port to listen on (default: 9876)
  WEBHOOK_SECRET  - GitHub webhook secret for signature validation (optional)
"""

import hashlib
import hmac
import logging
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("WEBHOOK_PORT", 9876))
SECRET = os.environ.get("WEBHOOK_SECRET", "")
WORKDIR = Path(__file__).resolve().parent
LOCKFILE = Path("/tmp/gakutoolkit.lock")
LOGFILE = WORKDIR / "webhook.log"

# Repos that trigger a run
WATCHED_REPOS = {
    "DreamGallery/Campus-adv-txts",
    "pinisok/gakumas-master-translation",
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
log = logging.getLogger("webhook")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not SECRET:
        return True  # no secret configured, skip validation
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def _is_running() -> bool:
    """Check if run.sh is already running via lock file + PID check."""
    if not LOCKFILE.exists():
        return False
    # Lock file exists — check if the process is actually alive
    try:
        pid_or_content = LOCKFILE.read_text().strip()
        if pid_or_content.isdigit():
            os.kill(int(pid_or_content), 0)
            return True
        # Lock file exists but no valid PID — still treat as running
        # (run.sh uses 'touch' without PID, so just check file existence)
        return True
    except (ProcessLookupError, ValueError):
        # PID not running — stale lock
        log.warning("Stale lock file found, removing")
        LOCKFILE.unlink(missing_ok=True)
        return False


def _trigger_run(repo: str, ref: str) -> dict:
    """Trigger run.sh in the background."""
    if _is_running():
        msg = f"Skipped: already running (lock exists). Trigger: {repo}@{ref}"
        log.info(msg)
        return {"status": "skipped", "reason": "already_running"}

    log.info(f"Triggering run.sh — repo={repo} ref={ref}")
    logfile = WORKDIR / f"output_webhook_{__import__('datetime').datetime.now():%Y%m%d_%H%M}.log"

    proc = subprocess.Popen(
        ["bash", "run.sh"],
        cwd=str(WORKDIR),
        stdout=open(logfile, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,  # detach from webhook process
    )
    log.info(f"run.sh started — PID={proc.pid}, log={logfile.name}")
    return {"status": "triggered", "pid": proc.pid, "log": logfile.name}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle GitHub webhook push events."""
    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.data, signature):
        log.warning("Invalid signature")
        abort(403, "Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        log.info("Ping received")
        return jsonify({"status": "pong"})

    if event != "push":
        log.info(f"Ignored event: {event}")
        return jsonify({"status": "ignored", "event": event})

    payload = request.get_json(silent=True)
    if not payload:
        abort(400, "Invalid JSON")

    repo = payload.get("repository", {}).get("full_name", "")
    ref = payload.get("ref", "")

    log.info(f"Push event: {repo} ref={ref}")

    # Only trigger on watched repos + main branch
    if repo not in WATCHED_REPOS:
        msg = f"Ignored: repo {repo} not in watch list"
        log.info(msg)
        return jsonify({"status": "ignored", "reason": "repo_not_watched"})

    if ref not in ("refs/heads/main", "refs/heads/master"):
        msg = f"Ignored: ref {ref} is not main/master"
        log.info(msg)
        return jsonify({"status": "ignored", "reason": "not_main_branch"})

    result = _trigger_run(repo, ref)
    return jsonify(result)


@app.route("/status", methods=["GET"])
def status():
    """Check if run.sh is currently running."""
    running = _is_running()
    return jsonify({"running": running, "lock_exists": LOCKFILE.exists()})


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(f"Starting webhook server on port {PORT}")
    log.info(f"Watching repos: {WATCHED_REPOS}")
    log.info(f"Work directory: {WORKDIR}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
