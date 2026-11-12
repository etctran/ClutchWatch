#!/usr/bin/env bash
# Tear down everything billable. Safe to run repeatedly.
set -uo pipefail
cd "$(dirname "$0")/.."
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
echo "Tearing down in $PROJECT/$REGION"
if [ -d infra/.terraform ]; then
  terraform -chdir=infra destroy -auto-approve -input=false -var "project=$PROJECT" -var "region=$REGION"
fi
echo "Remaining Redis instances (should be none):"
gcloud redis instances list --region "$REGION" --project "$PROJECT" 2>/dev/null
echo "Remaining Cloud Run services (should be none):"
gcloud run services list --region "$REGION" --project "$PROJECT" 2>/dev/null
