#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-europe-west2}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-vadim0x60/LeaveNowBot}"
PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"

if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
  echo "Select a Google Cloud project before running this setup." >&2
  exit 1
fi

STATE_BUCKET="${PROJECT_ID}-leavenowbot-tfstate"

echo "Setting up LeaveNowBot in ${PROJECT_ID} (${REGION})..."
gcloud services enable serviceusage.googleapis.com storage.googleapis.com \
  --project "${PROJECT_ID}" --quiet

if ! gcloud storage buckets describe "gs://${STATE_BUCKET}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${STATE_BUCKET}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --uniform-bucket-level-access \
    --quiet
fi
gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning --quiet

terraform -chdir=infra/bootstrap init \
  -backend-config="bucket=${STATE_BUCKET}" \
  -input=false

# The retired key-based setup created this account outside Terraform. Adopt it
# when migrating so the first browser setup does not fail or replace anything.
if ! terraform -chdir=infra/bootstrap state show google_service_account.deployer \
  >/dev/null 2>&1 && \
  gcloud iam service-accounts describe \
    "leavenowbot-github@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project "${PROJECT_ID}" >/dev/null 2>&1; then
  terraform -chdir=infra/bootstrap import \
    -var="project_id=${PROJECT_ID}" \
    -var="region=${REGION}" \
    -var="github_repository=${GITHUB_REPOSITORY}" \
    google_service_account.deployer \
    "projects/${PROJECT_ID}/serviceAccounts/leavenowbot-github@${PROJECT_ID}.iam.gserviceaccount.com"
fi

terraform -chdir=infra/bootstrap apply \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="github_repository=${GITHUB_REPOSITORY}" \
  -auto-approve \
  -input=false

has_enabled_version() {
  [[ -n "$(gcloud secrets versions list "$1" \
    --project "${PROJECT_ID}" \
    --filter='state=ENABLED' \
    --limit=1 \
    --format='value(name)')" ]]
}

add_prompted_secret() {
  local name="$1" prompt="$2" value
  if has_enabled_version "${name}"; then
    echo "Keeping the existing ${name} value."
    return
  fi
  while [[ -z "${value:-}" ]]; do
    read -r -s -p "${prompt}: " value
    echo
  done
  printf %s "${value}" | gcloud secrets versions add "${name}" \
    --project "${PROJECT_ID}" \
    --data-file=- \
    --quiet
  unset value
}

add_prompted_secret leavenowbot-telegram-token "Telegram bot token"
add_prompted_secret leavenowbot-maps-api-key "Google Routes API key"
add_prompted_secret leavenowbot-allowed-user-ids "Allowed Telegram user IDs (comma-separated)"

if has_enabled_version leavenowbot-webhook-secret; then
  echo "Keeping the existing leavenowbot-webhook-secret value."
else
  python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' | \
    gcloud secrets versions add leavenowbot-webhook-secret \
      --project "${PROJECT_ID}" \
      --data-file=- \
      --quiet
fi

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/leavenowbot/leavenowbot:$(git rev-parse HEAD)"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build --tag "${IMAGE}" .
docker push "${IMAGE}"

terraform -chdir=infra/app init \
  -backend-config="bucket=${STATE_BUCKET}" \
  -input=false
terraform -chdir=infra/app apply \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="image=${IMAGE}" \
  -auto-approve \
  -input=false

SERVICE_URL="$(terraform -chdir=infra/app output -raw service_url)"
curl --fail --retry 5 --retry-all-errors --retry-delay 2 "${SERVICE_URL%/}/healthz"
python3 scripts/set_webhook.py --project "${PROJECT_ID}" --service-url "${SERVICE_URL}"

WIF_PROVIDER="$(terraform -chdir=infra/bootstrap output -raw workload_identity_provider)"
WIF_SERVICE_ACCOUNT="$(terraform -chdir=infra/bootstrap output -raw deployer_service_account)"

cat <<EOF

LeaveNowBot is running at ${SERVICE_URL}

To enable automatic deployments, add these GitHub repository variables:
  WIF_PROVIDER=${WIF_PROVIDER}
  WIF_SERVICE_ACCOUNT=${WIF_SERVICE_ACCOUNT}

Repository variables: https://github.com/${GITHUB_REPOSITORY}/settings/variables/actions
EOF
