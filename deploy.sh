#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-europe-west2}"
SERVICE="leavenowbot"
QUEUE="leavenowbot-checks"
BOT_TIMEZONE="${BOT_TIMEZONE:-Europe/London}"

for command in gcloud python3 curl; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 1
  fi
done

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
  echo "Select a billing-enabled project first: gcloud config set project PROJECT_ID" >&2
  exit 1
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUNTIME_SA="leavenowbot-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
TASKS_SA="leavenowbot-tasks@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
SECRETS=(
  leavenowbot-telegram-token
  leavenowbot-maps-api-key
  leavenowbot-webhook-secret
  leavenowbot-allowed-user-ids
)

echo "Deploying LeaveNowBot to ${PROJECT_ID} in ${REGION}."
echo "Firestore's location is permanent; set REGION before the first deployment."

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  cloudtasks.googleapis.com \
  secretmanager.googleapis.com \
  routes.googleapis.com \
  apikeys.googleapis.com \
  iam.googleapis.com \
  --project="${PROJECT_ID}" \
  --quiet

if firestore_location="$(gcloud firestore databases describe \
  --database='(default)' \
  --project="${PROJECT_ID}" \
  --format='value(locationId)' 2>/dev/null)"; then
  if [[ "${firestore_location}" != "${REGION}" ]]; then
    echo "Firestore already uses ${firestore_location}; rerun with REGION=${firestore_location}." >&2
    exit 1
  fi
else
  gcloud firestore databases create \
    --database='(default)' \
    --location="${REGION}" \
    --type=firestore-native \
    --delete-protection \
    --project="${PROJECT_ID}" \
    --quiet
fi

if ! gcloud tasks queues describe "${QUEUE}" \
  --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud tasks queues create "${QUEUE}" \
    --location="${REGION}" \
    --max-concurrent-dispatches=1 \
    --max-dispatches-per-second=2 \
    --max-attempts=20 \
    --min-backoff=5s \
    --max-backoff=300s \
    --max-doublings=5 \
    --max-retry-duration=3600s \
    --project="${PROJECT_ID}" \
    --quiet
fi

ensure_service_account() {
  local account_id="$1" display_name="$2" email
  email="${account_id}@${PROJECT_ID}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "${email}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${account_id}" \
      --display-name="${display_name}" \
      --project="${PROJECT_ID}" \
      --quiet
  fi
}

project_has_binding() {
  local role="$1" member="$2"
  gcloud projects get-iam-policy "${PROJECT_ID}" \
    --flatten='bindings[].members' \
    --format='value(bindings.role,bindings.members)' | \
    grep -Fqx "$(printf '%s\t%s' "${role}" "${member}")"
}

ensure_project_binding() {
  local role="$1" member="$2"
  if ! project_has_binding "${role}" "${member}"; then
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="${member}" \
      --role="${role}" \
      --condition=None \
      --quiet >/dev/null
  fi
}

service_account_has_binding() {
  local service_account="$1" role="$2" member="$3"
  gcloud iam service-accounts get-iam-policy "${service_account}" \
    --project="${PROJECT_ID}" \
    --flatten='bindings[].members' \
    --format='value(bindings.role,bindings.members)' | \
    grep -Fqx "$(printf '%s\t%s' "${role}" "${member}")"
}

ensure_service_account_binding() {
  local service_account="$1" role="$2" member="$3"
  if ! service_account_has_binding "${service_account}" "${role}" "${member}"; then
    gcloud iam service-accounts add-iam-policy-binding "${service_account}" \
      --project="${PROJECT_ID}" \
      --member="${member}" \
      --role="${role}" \
      --condition=None \
      --quiet >/dev/null
  fi
}

ensure_service_account leavenowbot-runtime "LeaveNowBot Cloud Run runtime"
ensure_service_account leavenowbot-tasks "LeaveNowBot Cloud Tasks caller"

for _ in {1..12}; do
  if gcloud iam service-accounts describe "${BUILD_SA}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
if ! gcloud iam service-accounts describe "${BUILD_SA}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "The Compute Engine default service account ${BUILD_SA} does not exist." >&2
  echo "Create or restore it, then rerun this command." >&2
  exit 1
fi

ensure_project_binding roles/run.builder "serviceAccount:${BUILD_SA}"
ensure_project_binding roles/datastore.user "serviceAccount:${RUNTIME_SA}"
ensure_project_binding roles/cloudtasks.enqueuer "serviceAccount:${RUNTIME_SA}"
ensure_service_account_binding "${TASKS_SA}" roles/iam.serviceAccountUser \
  "serviceAccount:${RUNTIME_SA}"

ensure_secret() {
  local name="$1"
  if ! gcloud secrets describe "${name}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${name}" \
      --replication-policy=automatic \
      --project="${PROJECT_ID}" \
      --quiet
  fi
}

has_enabled_version() {
  local name="$1" version
  version="$(gcloud secrets versions list "${name}" \
    --project="${PROJECT_ID}" \
    --filter='state=ENABLED' \
    --limit=1 \
    --format='value(name)')"
  [[ -n "${version}" ]]
}

secret_has_binding() {
  local name="$1" role="$2" member="$3"
  gcloud secrets get-iam-policy "${name}" \
    --project="${PROJECT_ID}" \
    --flatten='bindings[].members' \
    --format='value(bindings.role,bindings.members)' | \
    grep -Fqx "$(printf '%s\t%s' "${role}" "${member}")"
}

for secret_name in "${SECRETS[@]}"; do
  ensure_secret "${secret_name}"
  if ! secret_has_binding "${secret_name}" roles/secretmanager.secretAccessor \
    "serviceAccount:${RUNTIME_SA}"; then
    gcloud secrets add-iam-policy-binding "${secret_name}" \
      --project="${PROJECT_ID}" \
      --member="serviceAccount:${RUNTIME_SA}" \
      --role=roles/secretmanager.secretAccessor \
      --condition=None \
      --quiet >/dev/null
  fi
done

if has_enabled_version leavenowbot-telegram-token; then
  echo "Keeping the existing Telegram token."
else
  telegram_token=""
  while [[ -z "${telegram_token}" ]]; do
    read -r -s -p "Telegram BotFather token: " telegram_token
    echo
  done
  printf '%s' "${telegram_token}" | gcloud secrets versions add \
    leavenowbot-telegram-token --project="${PROJECT_ID}" --data-file=- --quiet
  unset telegram_token
fi

if has_enabled_version leavenowbot-maps-api-key; then
  echo "Keeping the existing Routes API key."
else
  api_key_name="$(gcloud services api-keys list \
    --project="${PROJECT_ID}" \
    --filter='displayName=LeaveNowBot Routes' \
    --limit=1 \
    --format='value(name)')"
  if [[ -z "${api_key_name}" ]]; then
    api_key_name="$(gcloud services api-keys create \
      --display-name='LeaveNowBot Routes' \
      --api-target=service=routes.googleapis.com \
      --project="${PROJECT_ID}" \
      --format='value(name)')"
  fi
  maps_api_key="$(gcloud services api-keys get-key-string "${api_key_name}" \
    --project="${PROJECT_ID}" --format='value(keyString)')"
  printf '%s' "${maps_api_key}" | gcloud secrets versions add \
    leavenowbot-maps-api-key --project="${PROJECT_ID}" --data-file=- --quiet
  unset maps_api_key
fi

if ! has_enabled_version leavenowbot-webhook-secret; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' | \
    gcloud secrets versions add leavenowbot-webhook-secret \
      --project="${PROJECT_ID}" --data-file=- --quiet
fi

if has_enabled_version leavenowbot-allowed-user-ids; then
  echo "Keeping the existing allowed Telegram user IDs."
else
  if [[ -n "${ALLOWED_USER_IDS:-}" ]]; then
    allowed_ids="$(printf '%s' "${ALLOWED_USER_IDS}" | tr -d '[:space:]')"
  else
    telegram_token="$(gcloud secrets versions access latest \
      --secret=leavenowbot-telegram-token --project="${PROJECT_ID}")"
    allowed_ids="$(TELEGRAM_TOKEN="${telegram_token}" python3 - <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

token = os.environ["TELEGRAM_TOKEN"]
base = f"https://api.telegram.org/bot{token}/"


def call(method: str, **values: str) -> dict:
    request = urllib.request.Request(
        base + method,
        data=urllib.parse.urlencode(values).encode(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Telegram request {method} failed with HTTP {error.code}.") from None
    except urllib.error.URLError:
        raise SystemExit(f"Telegram request {method} could not connect.") from None
    if not result.get("ok"):
        raise SystemExit(f"Telegram rejected {method}.")
    return result


call("deleteWebhook", drop_pending_updates="true")
print("Send /start to your bot now. Waiting up to three minutes...", file=sys.stderr)
deadline = time.monotonic() + 180
offset = None
while time.monotonic() < deadline:
    values = {"timeout": "20", "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        values["offset"] = str(offset)
    updates = call("getUpdates", **values)["result"]
    for update in updates:
        offset = update["update_id"] + 1
        message = update.get("message", {})
        if message.get("text", "").split("@", 1)[0] == "/start":
            user_id = message.get("from", {}).get("id")
            if isinstance(user_id, int) and user_id > 0:
                print(user_id)
                raise SystemExit(0)
raise SystemExit("No /start message arrived. Send it to the bot and rerun ./deploy.sh.")
PY
)"
    unset telegram_token TELEGRAM_TOKEN
  fi
  if [[ ! "${allowed_ids}" =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ ]]; then
    echo "ALLOWED_USER_IDS must contain comma-separated positive numeric Telegram user IDs." >&2
    exit 1
  fi
  printf '%s' "${allowed_ids}" | gcloud secrets versions add \
    leavenowbot-allowed-user-ids --project="${PROJECT_ID}" --data-file=- --quiet
fi

deploy_args=(
  "${SERVICE}"
  --source=.
  --region="${REGION}"
  --project="${PROJECT_ID}"
  --service-account="${RUNTIME_SA}"
  --allow-unauthenticated
  --min=0
  --max=1
  --concurrency=1
  --timeout=60s
  --cpu=1
  --memory=512Mi
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},BOT_TIMEZONE=${BOT_TIMEZONE},TASK_LOCATION=${REGION},TASK_QUEUE=${QUEUE},TASK_SERVICE_ACCOUNT=${TASKS_SA}"
  --set-secrets="ALLOWED_USER_IDS=leavenowbot-allowed-user-ids:latest,TELEGRAM_BOT_TOKEN=leavenowbot-telegram-token:latest,GOOGLE_MAPS_API_KEY=leavenowbot-maps-api-key:latest,TELEGRAM_WEBHOOK_SECRET=leavenowbot-webhook-secret:latest"
  --quiet
)
if gcloud run deploy --help 2>/dev/null | grep -q -- '--cpu-throttling'; then
  deploy_args+=(--cpu-throttling)
fi
if gcloud run deploy --help 2>/dev/null | grep -q -- '--cpu-boost'; then
  deploy_args+=(--cpu-boost)
fi

gcloud run deploy "${deploy_args[@]}"

SERVICE_URL="$(gcloud run services describe "${SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"

run_has_binding() {
  local role="$1" member="$2"
  gcloud run services get-iam-policy "${SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --flatten='bindings[].members' \
    --format='value(bindings.role,bindings.members)' | \
    grep -Fqx "$(printf '%s\t%s' "${role}" "${member}")"
}

for invoker in allUsers "serviceAccount:${TASKS_SA}"; do
  if ! run_has_binding roles/run.invoker "${invoker}"; then
    gcloud run services add-iam-policy-binding "${SERVICE}" \
      --region="${REGION}" \
      --project="${PROJECT_ID}" \
      --member="${invoker}" \
      --role=roles/run.invoker \
      --condition=None \
      --quiet >/dev/null
  fi
done

curl --fail --show-error --retry 5 --retry-all-errors --retry-delay 2 \
  "${SERVICE_URL%/}/healthz"
python3 scripts/set_webhook.py --project "${PROJECT_ID}" --service-url "${SERVICE_URL}"

echo
echo "LeaveNowBot is deployed at ${SERVICE_URL}"
