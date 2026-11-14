#!/usr/bin/env bash
# T6: full-season replay, and deploy a new processor revision mid-replay, once <at-events>
# events of the run are in raw_events (progress-based, so laptop sleep can't skew it; run under
# `caffeinate -i` anyway so the watcher itself keeps running).
#   caffeinate -i bench/run_restart.sh <run-tag> <events-per-sec> <at-events>
set -euo pipefail
TAG="$1"; RATE="$2"; AT="$3"
REGION="${REGION:-us-central1}"
ts() { python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat(timespec="milliseconds"))'; }
"$(dirname "$0")/run_load.sh" "$TAG" "$RATE" &
LOAD=$!
while :; do
  n=$(bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) FROM clutchwatch.raw_events WHERE STARTS_WITH(game_id,'$TAG-')" 2>/dev/null | tail -1)
  [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge "$AT" ] && break
  sleep 10
done
echo "redeploy_start $(ts) published_so_far=$n"
gcloud run services update processor --region "$REGION" --update-env-vars "RESTART_MARK=$TAG-$(date +%s)" --quiet 2>&1 | tail -1
echo "redeploy_ready $(ts) $(gcloud run services describe processor --region "$REGION" --format='value(status.latestReadyRevisionName)')"
wait $LOAD
