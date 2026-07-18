#!/usr/bin/env bash
# Provision role-scoped Google WIF providers and least-privilege service accounts.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 PROJECT_ID JWKS_DIRECTORY CREDENTIAL_OUTPUT_DIRECTORY" >&2
  exit 2
fi

PROJECT_ID="$1"
JWKS_DIR="$2"
CREDENTIAL_DIR="$3"
POOL_ID="sclib-production"
BACKUP_BUCKET="sclib-jzis-backups"
APP_BUCKET="sclib-jzis"

command -v gcloud >/dev/null
command -v jq >/dev/null
[[ -d "$JWKS_DIR" ]]
mkdir -p "$CREDENTIAL_DIR"

gcloud services enable \
  aiplatform.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  serviceusage.googleapis.com \
  sts.googleapis.com \
  storage.googleapis.com \
  --project="$PROJECT_ID" --quiet

PROJECT_NUMBER="$(
  gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)'
)"
[[ "$PROJECT_NUMBER" =~ ^[1-9][0-9]+$ ]]

if ! gcloud iam workload-identity-pools describe "$POOL_ID" \
  --project="$PROJECT_ID" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --project="$PROJECT_ID" \
    --location=global \
    --display-name="SCLib production VPS2" \
    --description="Short-lived identities for SCLib VPS2 workloads"
fi

for role in api ingestion backup; do
  service_account="sclib-$role@$PROJECT_ID.iam.gserviceaccount.com"
  provider="vps2-$role"
  issuer="https://api.jzis.org/sclib-identity/$role"
  subject="sclib-$role-vps2"
  jwks="$JWKS_DIR/$role.jwks.json"
  test -s "$jwks"
  jq --exit-status '
    (.keys | length) == 1 and
    .keys[0].alg == "RS256" and
    .keys[0].kty == "RSA" and
    .keys[0].use == "sig"
  ' "$jwks" >/dev/null

  if ! gcloud iam service-accounts describe "$service_account" \
    --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "sclib-$role" \
      --project="$PROJECT_ID" \
      --display-name="SCLib production $role"
  fi

  provider_args=(
    "$provider"
    --project="$PROJECT_ID"
    --location=global
    --workload-identity-pool="$POOL_ID"
    --issuer-uri="$issuer"
    --jwk-json-path="$jwks"
    --attribute-mapping="google.subject=assertion.sub,attribute.sclib_role=assertion.sclib_role"
    --attribute-condition="assertion.sub == '$subject' && assertion.sclib_role == '$role'"
  )
  if gcloud iam workload-identity-pools providers describe "$provider" \
    --project="$PROJECT_ID" --location=global \
    --workload-identity-pool="$POOL_ID" >/dev/null 2>&1; then
    gcloud iam workload-identity-pools providers update-oidc "${provider_args[@]}"
  else
    gcloud iam workload-identity-pools providers create-oidc "${provider_args[@]}" \
      --display-name="SCLib VPS2 $role"
  fi

  principal="principal://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/subject/$subject"
  gcloud iam service-accounts add-iam-policy-binding "$service_account" \
    --project="$PROJECT_ID" \
    --role=roles/iam.workloadIdentityUser \
    --member="$principal" >/dev/null

  provider_resource="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/providers/$provider"
  gcloud iam workload-identity-pools create-cred-config "$provider_resource" \
    --service-account="$service_account" \
    --credential-source-file="/var/run/sclib-identity/$role/subject.jwt" \
    --credential-source-type=text \
    --output-file="$CREDENTIAL_DIR/$role-external-account.json"
done

for binding in \
  "sclib-api:roles/aiplatform.user" \
  "sclib-api:roles/serviceusage.serviceUsageConsumer" \
  "sclib-ingestion:roles/aiplatform.editor" \
  "sclib-ingestion:roles/serviceusage.serviceUsageConsumer" \
  "sclib-backup:roles/serviceusage.serviceUsageConsumer"; do
  account="${binding%%:*}@$PROJECT_ID.iam.gserviceaccount.com"
  role="${binding#*:}"
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$account" \
    --role="$role" \
    --condition=None >/dev/null
done

if ! gcloud storage buckets describe "gs://$BACKUP_BUCKET" \
  --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BACKUP_BUCKET" \
    --project="$PROJECT_ID" \
    --location=us-central1 \
    --default-storage-class=NEARLINE \
    --uniform-bucket-level-access
fi
gcloud storage buckets update "gs://$BACKUP_BUCKET" \
  --project="$PROJECT_ID" --versioning --retention-period=35d >/dev/null

gcloud storage buckets add-iam-policy-binding "gs://$APP_BUCKET" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:sclib-ingestion@$PROJECT_ID.iam.gserviceaccount.com" \
  --role=roles/storage.objectAdmin >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$BACKUP_BUCKET" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:sclib-backup@$PROJECT_ID.iam.gserviceaccount.com" \
  --role=roles/storage.objectAdmin >/dev/null

echo "PROJECT_NUMBER=$PROJECT_NUMBER"
echo "WIF_POOL=$POOL_ID"
echo "CREDENTIAL_DIR=$CREDENTIAL_DIR"
