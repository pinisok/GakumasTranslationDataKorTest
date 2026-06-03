#!/bin/bash
set -e

echo $(date "+%Y-%m-%d %H:%M:%S")

# 잠금 — 동시 실행 방지 (flock 기반: 프로세스가 죽으면 커널이 자동 해제)
# 파일 자체는 webhook_server.py / submodule_watcher.py 가 PID 검증용으로 읽으므로
# 정상 종료 시에만 trap 으로 정리. 비정상 종료 시에도 flock 은 자동 해제되며,
# webhook/watcher 가 dead PID 감지 후 stale 락 정리.
LOCKFILE="/tmp/gakutoolkit.lock"
LOCK_FD=200
eval "exec ${LOCK_FD}>\"\$LOCKFILE\""
if ! flock -n "$LOCK_FD"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Already running (lock held by another process) — skipping"
    exit 0
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

# 데이터 동기화 — campus 호출은 /root/worker/GakuToolkit/campus-cron.sh 가 단일
# 소유자. 여기서는 단순 reader (campus 미호출). cache 가 비어있거나 너무 옛 데이터면
# campus_sync 가 "source empty" 로 abort 하므로 다음 campus-cron tick 후 재시도.
# campus-cron 이 실패해 cache 가 stale 상태이면 fallback 으로 git submodule 사용 가능:
#   python3 scripts/campus_sync.py fallback masterdb
#   python3 scripts/campus_sync.py fallback adv
python3 scripts/campus_sync.py sync masterdb --skip-campus || { echo "❌ masterdb sync 실패"; exit 1; }
python3 scripts/campus_sync.py sync adv     --skip-campus || { echo "❌ adv sync 실패";     exit 1; }

# campus diff 알림 — 변경이 있으면 NanoClaw Discord DM으로 요약 전송
# (best-effort: Discord가 죽어도 번역 파이프라인은 계속 진행)
node scripts/notify_campus_diff.mjs || echo "⚠ campus diff notification failed"

# output 서브모듈은 여전히 git (push 대상이므로 git 워크플로우 유지)
git submodule update --init --remote -- output

# masterdb 변환 결과 정리 (campus의 orig 이외 산출물)
rm -f ./res/masterdb/data/*
rm -rf ./res/masterdb/gakumasu-diff/json
rm -rf ./res/masterdb/pretranslate_todo/

# 7일 이상 된 로그 파일 정리
find . -maxdepth 1 -name "output_python_*.log" -mtime +7 -delete 2>/dev/null || true

# output 서브모듈 현재 상태 기록 (Phase 1 실패 시 복구용)
OUTPUT_HEAD=""
if [ -d output/.git ]; then
    OUTPUT_HEAD=$(git -C output rev-parse HEAD 2>/dev/null || echo "")
fi

# 메인 실행
if ! python3 main.py; then
    echo "❌ main.py 실패 — output 복구 중"
    if [ -n "$OUTPUT_HEAD" ] && [ -d output/.git ]; then
        git -C output checkout -- . 2>/dev/null || true
        echo "  ✓ output 서브모듈을 실행 전 상태로 복원"
    fi
    exit 1
fi

# 변경사항이 있을 때만 커밋/푸시
cd output
if [ -n "$(git status --porcelain)" ]; then
    git add --all
    git commit -m "Update translate $(date '+%Y-%m-%d %H:%M')"
    git push origin main
else
    echo "No changes to push"
fi
