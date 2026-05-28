"""Campus sync — pull ADV txt and master yaml from campus output.

Replaces `git submodule update` for:
  - res/adv/Resource/         ← /root/worker/campus/cache/raw/adv_*.txt
  - res/masterdb/gakumasu-diff/orig/ ← /root/worker/campus/cache/masterYaml/*.yaml

Both sources are produced byte-perfect identical to the previous git mirrors
(DreamGallery/Campus-adv-txts, pinisok/gakumas-master-translation), so no
format conversion is required — just file copy + manifest tracking.

Manifest layout (res/.manifest/):
  {target}.json         — current snapshot (path → mtime/size/sha256)
  {target}.diff.json    — last sync diff (added/modified/removed)
  {target}.journal.jsonl — append-only sync history (one event per line)

Subcommands:
  sync <target> [--skip-campus]  Run campus → copy files → write manifest/diff/journal
  diff <target>                  Show last diff JSON
  journal <target> [--limit N]   Show recent journal entries (default 10)
  fallback <target>              Fall back to `git submodule update --remote`
  status                         Show campus revision + per-target last sync summary

Targets: adv | masterdb

Exit codes:
  0  success (sync done, no source produced, or no diff change)
  1  campus failure (after fallback attempt) or empty source
  2  invalid args
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORK = Path("/root/worker/GakuToolkit")
CAMPUS = Path("/root/worker/campus")
MANIFEST_DIR = WORK / "res" / ".manifest"

# /tmp/campus.lock 은 GakuToolkit + gkms-texture-tools 가 공유한다. 두 시스템 모두
# 같은 /root/worker/campus 를 쓰므로, 한쪽이 campus 를 실행하거나 cache 를 읽는
# 동안 다른 쪽은 대기해야 (cache/assets 가 cleanup 되거나 octo 세션이 겹치는
# 사고를 막는다). cronjob.sh 의 flock 호출도 같은 경로를 가리킨다.
LOCK_DIR = Path("/tmp")
CAMPUS_LOCK = LOCK_DIR / "campus.lock"
CAMPUS_LOCK_TIMEOUT = int(os.environ.get("CAMPUS_LOCK_TIMEOUT", "1800"))  # 30분


@contextlib.contextmanager
def _file_lock(lock_path: Path, label: str, timeout: int = CAMPUS_LOCK_TIMEOUT):
    """Acquire exclusive flock with bounded wait — blocks until other holder frees it.

    Used so two systems sharing /root/worker/campus serialize cleanly:
      - GakuToolkit campus_sync (this script)
      - gkms-texture-tools cronjob.sh (uses `flock` on the same path)

    Aborts with exit code 1 if the timeout elapses, so a hung holder cannot
    silently strand the caller. PID is recorded inside the lock file for
    operator debugging; the real lock is the flock, not the file contents.
    """
    import time

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("w")
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            now = time.monotonic()
            if now >= deadline:
                fh.close()
                print(f"[lock] {label}: timed out after {timeout}s waiting for "
                      f"{lock_path} — abort", file=sys.stderr)
                raise SystemExit(1)
            if not announced:
                holder = ""
                try:
                    holder = lock_path.read_text().strip()
                except Exception:
                    pass
                print(f"[lock] {label}: held by PID {holder or '?'} — "
                      f"waiting up to {timeout}s", file=sys.stderr)
                announced = True
            time.sleep(min(15, max(2, int(deadline - now) // 10)))
    try:
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()

TARGETS: Dict[str, Dict[str, Any]] = {
    "adv": {
        "source_dir": CAMPUS / "cache" / "raw",
        "source_pattern": "adv_*.txt",
        "target_dir": WORK / "res" / "adv" / "Resource",
        # ADV txts live in raw/, populated as a side effect of `-ab`. We do not
        # force a fresh fetch here — caller decides via --skip-campus.
        "campus_flags": ["-ab"],
        "submodule": "res/adv",
    },
    "masterdb": {
        "source_dir": CAMPUS / "cache" / "masterYaml",
        "source_pattern": "*.yaml",
        "target_dir": WORK / "res" / "masterdb" / "gakumasu-diff" / "orig",
        "campus_flags": ["-db"],
        "submodule": "res/masterdb",
    },
}

# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _file_meta(p: Path) -> Dict[str, Any]:
    stat = p.stat()
    sha = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return {"mtime": int(stat.st_mtime), "size": stat.st_size, "sha256": sha.hexdigest()}


def _campus_version() -> Dict[str, Any]:
    """Read campus config.yaml for masterVersion / appVersion / octoCacheRevision."""
    cfg = CAMPUS / "config.yaml"
    if not cfg.exists():
        return {}
    info: Dict[str, Any] = {}
    for line in cfg.read_text().splitlines():
        line = line.strip()
        for key in ("appVersion", "masterVersion", "octoCacheRevision"):
            if line.startswith(f"{key}:"):
                info[key] = line.split(":", 1)[1].strip()
    return info


def build_manifest(source_dir: Path, pattern: str) -> Dict[str, Any]:
    """Snapshot all files matching pattern under source_dir."""
    files = {}
    if source_dir.exists():
        for p in sorted(source_dir.glob(pattern)):
            if p.is_file():
                files[p.name] = _file_meta(p)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir),
        "pattern": pattern,
        "file_count": len(files),
        "campus": _campus_version(),
        "files": files,
    }


def diff_manifests(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Compute added/modified/removed between two manifests."""
    old_files = old.get("files", {})
    new_files = new.get("files", {})

    added = sorted(set(new_files) - set(old_files))
    removed = sorted(set(old_files) - set(new_files))
    modified = []
    for name in sorted(set(old_files) & set(new_files)):
        if old_files[name]["sha256"] != new_files[name]["sha256"]:
            modified.append({
                "path": name,
                "old": old_files[name],
                "new": new_files[name],
            })

    return {
        "previous_generated_at": old.get("generated_at"),
        "current_generated_at": new.get("generated_at"),
        "previous_campus": old.get("campus", {}),
        "current_campus": new.get("campus", {}),
        "added": added,
        "removed": removed,
        "modified": modified,
        "summary": {"+": len(added), "-": len(removed), "~": len(modified)},
    }


# ---------------------------------------------------------------------------
# Campus invocation & file sync
# ---------------------------------------------------------------------------


def run_campus(flags: List[str]) -> int:
    """Run campus with given flags. Returns exit code.

    Caller (cmd_sync) holds CAMPUS_LOCK for the entire sync — including this
    invocation — so we do not re-acquire here.
    """
    cmd = ["env", "CGO_ENABLED=1", "go", "run", "."] + list(flags)
    print(f"[campus] cd {CAMPUS} && {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(CAMPUS))
    return proc.returncode


def sync_files(source_dir: Path, pattern: str, target_dir: Path, removed: List[str]) -> None:
    """Copy all source files to target_dir; delete files in removed list."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for src in source_dir.glob(pattern):
        if src.is_file():
            shutil.copy2(src, target_dir / src.name)
    for name in removed:
        (target_dir / name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _load_manifest(target: str) -> Dict[str, Any]:
    p = MANIFEST_DIR / f"{target}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"files": {}}


def _save_manifest(target: str, manifest: Dict[str, Any]) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    (MANIFEST_DIR / f"{target}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )


def _save_diff(target: str, diff: Dict[str, Any]) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    (MANIFEST_DIR / f"{target}.diff.json").write_text(
        json.dumps(diff, ensure_ascii=False, indent=2)
    )


def _append_journal(target: str, diff: Dict[str, Any], campus_exit: int, used_fallback: bool) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    event = {
        "synced_at": diff["current_generated_at"],
        "previous_synced_at": diff.get("previous_generated_at"),
        "campus_exit": campus_exit,
        "used_fallback": used_fallback,
        "campus_version_change": {
            "from": diff.get("previous_campus", {}),
            "to": diff.get("current_campus", {}),
        },
        "summary": diff["summary"],
        "samples": {
            "added": diff["added"][:5],
            "removed": diff["removed"][:5],
            "modified": [m["path"] for m in diff["modified"][:5]],
        },
    }
    with (MANIFEST_DIR / f"{target}.journal.jsonl").open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_sync(target: str, skip_campus: bool = False) -> int:
    spec = TARGETS[target]
    source_dir: Path = spec["source_dir"]
    pattern: str = spec["source_pattern"]
    target_dir: Path = spec["target_dir"]

    # Hold CAMPUS_LOCK for the whole critical section — covers both the
    # `go run campus` invocation and the cache → res copy that follows. This
    # prevents gkms-texture-tools' cronjob from running `campus -ab` (which
    # rewrites cache/raw) or its step-4 cleanup (which wipes cache/assets)
    # in the middle of our sync.
    with _file_lock(CAMPUS_LOCK, f"campus_sync {target}"):
        return _do_sync(target, spec, source_dir, pattern, target_dir, skip_campus)


def _do_sync(target: str, spec: Dict[str, Any], source_dir: Path, pattern: str,
             target_dir: Path, skip_campus: bool) -> int:
    used_fallback = False
    campus_exit = 0

    if not skip_campus:
        campus_exit = run_campus(spec["campus_flags"])
        if campus_exit != 0:
            print(f"[campus] failed (exit {campus_exit}) — falling back to git submodule",
                  file=sys.stderr)
            rc = cmd_fallback(target)
            if rc != 0:
                return rc
            used_fallback = True

    new_manifest = build_manifest(source_dir, pattern)
    if not used_fallback and new_manifest["file_count"] == 0:
        print(f"[sync] source empty ({source_dir}) — abort to avoid wiping target",
              file=sys.stderr)
        return 1

    prev_manifest = _load_manifest(target)
    diff = diff_manifests(prev_manifest, new_manifest)
    s = diff["summary"]
    print(f"[sync] {target}: +{s['+']} ~{s['~']} -{s['-']}  "
          f"(source files: {new_manifest['file_count']})")

    if not used_fallback:
        sync_files(source_dir, pattern, target_dir, diff["removed"])

    _save_manifest(target, new_manifest)
    _save_diff(target, diff)
    _append_journal(target, diff, campus_exit, used_fallback)
    return 0


def cmd_diff(target: str) -> int:
    p = MANIFEST_DIR / f"{target}.diff.json"
    if not p.exists():
        print(f"No diff yet for {target}")
        return 0
    print(p.read_text())
    return 0


def cmd_journal(target: str, limit: int) -> int:
    p = MANIFEST_DIR / f"{target}.journal.jsonl"
    if not p.exists():
        print(f"No journal for {target}")
        return 0
    lines = p.read_text().splitlines()
    for line in lines[-limit:]:
        print(line)
    return 0


def cmd_fallback(target: str) -> int:
    spec = TARGETS[target]
    sub = spec["submodule"]
    print(f"[fallback] git submodule update --init --remote -- {sub}")
    return subprocess.call(
        ["git", "submodule", "update", "--init", "--remote", "--", sub],
        cwd=str(WORK),
    )


def cmd_status() -> int:
    print("campus:", json.dumps(_campus_version(), ensure_ascii=False))
    for target in TARGETS:
        diff_path = MANIFEST_DIR / f"{target}.diff.json"
        if not diff_path.exists():
            print(f"  {target}: never synced")
            continue
        diff = json.loads(diff_path.read_text())
        s = diff["summary"]
        print(f"  {target}: last sync @ {diff['current_generated_at']}  "
              f"+{s['+']} ~{s['~']} -{s['-']}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync")
    p.add_argument("target", choices=list(TARGETS))
    p.add_argument("--skip-campus", action="store_true",
                   help="Don't run campus; sync from existing cache")

    p = sub.add_parser("diff")
    p.add_argument("target", choices=list(TARGETS))

    p = sub.add_parser("journal")
    p.add_argument("target", choices=list(TARGETS))
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("fallback")
    p.add_argument("target", choices=list(TARGETS))

    sub.add_parser("status")

    args = parser.parse_args()
    if args.cmd == "sync":
        return cmd_sync(args.target, skip_campus=args.skip_campus)
    if args.cmd == "diff":
        return cmd_diff(args.target)
    if args.cmd == "journal":
        return cmd_journal(args.target, limit=args.limit)
    if args.cmd == "fallback":
        return cmd_fallback(args.target)
    if args.cmd == "status":
        return cmd_status()
    return 2


if __name__ == "__main__":
    sys.exit(main())
