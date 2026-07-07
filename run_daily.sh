#!/usr/bin/env bash
# 매일 자동 페이퍼 트레이딩 — 평일 장마감 후 실행(크론).
# 텔레그램 발송은 환경변수 KQ_CHAT/KQ_KEY 필요(크론 라인에서 주입, 소스엔 비밀 없음).
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")"

# 중복 실행 방지
exec 9>/tmp/kquant_daily.lock
flock -n 9 || { echo "$(date) 이미 실행 중, 스킵"; exit 0; }

source .venv/bin/activate
ARGS="${KQ_ARGS:---market KOSPI --top 20}"
NOTIFY=""
[ -n "${KQ_CHAT:-}" ] && [ -n "${KQ_KEY:-}" ] && NOTIFY="--notify"

echo "===== $(date '+%F %T %Z') 페이퍼 실행 ($ARGS $NOTIFY) ====="
python run.py paper $ARGS $NOTIFY
echo "----- 계좌 현황 -----"
python run.py account
echo "===== 완료 $(date '+%T') ====="
