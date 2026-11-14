#!/usr/bin/env bash
# Roll an image out to every Cloud Run service/job that currently exists (skips torn-down ones).
# Used by CI and by deploy.sh, so there is one release path.
#   scripts/release.sh <image>
set -euo pipefail
IMG="$1"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
G=(--project "$PROJECT" --region "$REGION" --quiet)
for s in processor notifier live-poller; do
  if gcloud run services describe "$s" "${G[@]}" >/dev/null 2>&1; then
    gcloud run services update "$s" --image "$IMG" "${G[@]}" 2>&1 | tail -1
  else
    echo "skip service $s (not deployed)"
  fi
done
if gcloud run jobs describe replayer "${G[@]}" >/dev/null 2>&1; then
  gcloud run jobs update replayer --image "$IMG" "${G[@]}" 2>&1 | tail -1
else
  echo "skip job replayer (not deployed)"
fi
