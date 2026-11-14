#!/usr/bin/env bash
# Tear down billable resources. Safe to run repeatedly.
#   scripts/teardown.sh          destroy everything (incl. BigQuery data)
#   scripts/teardown.sh redis    destroy only Memorystore (the one resource that bills while idle)
#                                and what depends on it (processor/notifier services + their push
#                                subscriptions); keeps BigQuery results queryable. deploy.sh restores.
set -uo pipefail
cd "$(dirname "$0")/.."
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
VARS=(-var "project=$PROJECT" -var "region=$REGION")
echo "Tearing down (${1:-all}) in $PROJECT/$REGION"
if [ -d infra/.terraform ]; then
  if [ "${1:-}" = "redis" ]; then
    terraform -chdir=infra destroy -auto-approve -input=false "${VARS[@]}" -target=google_redis_instance.state
  else
    terraform -chdir=infra destroy -auto-approve -input=false "${VARS[@]}"
  fi
fi
echo "Remaining Redis instances (should be none):"
gcloud redis instances list --region "$REGION" --project "$PROJECT" 2>/dev/null
echo "Remaining Cloud Run services:"
gcloud run services list --region "$REGION" --project "$PROJECT" 2>/dev/null
