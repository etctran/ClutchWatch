#!/usr/bin/env bash
# Tear down everything billable. Safe to run repeatedly.
set -uo pipefail
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
echo "Tearing down in $PROJECT/$REGION"
if [ -d "$(dirname "$0")/../infra/.terraform" ]; then
  terraform -chdir="$(dirname "$0")/../infra" destroy -auto-approve -var "project=$PROJECT" -var "region=$REGION"
fi
gcloud run services delete clutchwatch-smoke --region "$REGION" --project "$PROJECT" --quiet 2>/dev/null || true
gcloud artifacts repositories delete cloud-run-source-deploy --location "$REGION" --project "$PROJECT" --quiet 2>/dev/null || true
echo "Remaining Redis instances (should be none):"
gcloud redis instances list --region "$REGION" --project "$PROJECT" 2>/dev/null || true
