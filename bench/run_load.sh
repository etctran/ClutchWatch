#!/usr/bin/env bash
# Replay the full 2024-25 season from the Cloud Run Job (Google clocks) at a fixed rate.
#   SEASON=2024 bench/run_load.sh <run-tag> <events-per-sec> [extra replayer flags, comma-separated]
# All 1,230 games start together (--align); see docs/DECISIONS.md for why.
set -euo pipefail
TAG="$1"; RATE="$2"; EXTRA="${3:-}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
ARGS="--csv,data/replay/season_${SEASON:-2024}.parquet,--topic,projects/$PROJECT/topics/game-events,--target-rate,$RATE,--align,--run-tag,$TAG"
[ -n "$EXTRA" ] && ARGS="$ARGS,$EXTRA"
date -u +"start %Y-%m-%dT%H:%M:%SZ"
gcloud run jobs execute replayer --project "$PROJECT" --region "$REGION" --wait --args="$ARGS"
date -u +"end   %Y-%m-%dT%H:%M:%SZ"
