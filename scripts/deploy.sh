#!/usr/bin/env bash
# Stand everything up: image repo -> build image -> terraform apply.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
VARS=(-var "project=$PROJECT" -var "region=$REGION" ${TF_EXTRA_VARS:-})
tf() { terraform -chdir=infra "$@"; }
[ -f data/replay/season_2024.parquet ] || SEASONS=2024 ./scripts/fetch_data.sh

tf init -input=false >/dev/null
tf apply -auto-approve -input=false "${VARS[@]}" -target=google_artifact_registry_repository.images
REPO="$REGION-docker.pkg.dev/$PROJECT/clutchwatch"
TAG="$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- . ':!infra' || echo "-dirty$(date +%s)")"
gcloud builds submit --project "$PROJECT" --region "$REGION" --tag "$REPO/pipeline:$TAG" .
tf apply -auto-approve -input=false "${VARS[@]}" -var "image=$REPO/pipeline:$TAG"
# Terraform ignores image changes on existing services (CI owns them); roll the new one out.
./scripts/release.sh "$REPO/pipeline:$TAG"
tf output
