# LeaveNowBot

A personal Telegram bot that tells you when to stop wandering and leave for a destination by public transport. It runs on Google Cloud Run, scales to zero while idle, and uses Google Routes for transit estimates.

## Use it

1. Send a destination pin using Telegram’s Location attachment (a venue also works).
2. Send the time to be there, such as `18:30`.
3. Share your live location in the same private chat.

`18:30` means today in `Europe/London` by default. For another day, send `2026-10-01 18:30`; when travelling, you can supply an explicit offset, such as `2026-10-01T18:30+02:00`. The bot confirms the date and timezone. Past times are rejected rather than silently treated as tomorrow. Clock-change ambiguities require an explicit offset.

The bot maintains one status message with the journey, scheduled arrival, leave-by time, and estimated wandering budget. It sends separate notifications when 15 minutes or fewer remain and at **LEAVE NOW**. Each alert level is sent once per trip, even if the route later improves.

- `/trip`: start over with a new destination pin and time.
- `/status`: refresh the existing status message.
- `/cancel`: stop tracking and delete the saved trip and location.
- `/help` or `/start`: instructions.

## Architecture

Telegram sends message and edited-message updates to an authenticated Cloud Run webhook. Trip state lives in Firestore. While a location is fresh, each request creates one authenticated Cloud Task for the next 30-second check; that task refreshes the trip and schedules its successor. A newer Telegram update supersedes the old task with a token stored on the trip, so stale deliveries are no-ops. Once the location is stale, the service sleeps until the next alert or deadline unless a new location webhook wakes it sooner.

Cloud Run has zero minimum instances, one maximum instance, and a request concurrency of one. This preserves the bot’s serialized state machine while letting it scale to zero. Telegram requests carry a webhook secret. Task requests carry a Google-signed OIDC token for a dedicated service account and are checked again against the current task token.

## Deploy to Google Cloud

The GitHub Actions workflow handles the first deployment as well as later updates. It creates remote Terraform state, provisions the Google Cloud infrastructure, initializes the application secrets, builds the image, deploys Cloud Run, checks `/healthz`, and registers the Telegram webhook. It runs on every push to `master` and can also be started manually from GitHub’s Actions page.

The only infrastructure prerequisite is a billing-enabled Google Cloud project and a service-account credential authorized to provision resources in it. From an account with project-owner access, install `gcloud` and `gh`, then run:

```sh
export PROJECT_ID=your-project-id
gcloud config set project "$PROJECT_ID"
export DEPLOYER="leavenowbot-github@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts create leavenowbot-github \
  --display-name="LeaveNowBot GitHub deployer"
for ROLE in \
  roles/artifactregistry.admin \
  roles/cloudtasks.admin \
  roles/datastore.owner \
  roles/iam.serviceAccountAdmin \
  roles/iam.serviceAccountUser \
  roles/resourcemanager.projectIamAdmin \
  roles/run.admin \
  roles/secretmanager.admin \
  roles/secretmanager.secretAccessor \
  roles/serviceusage.serviceUsageAdmin \
  roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOYER}" --role="$ROLE"
done
```

Create a key and add the five required repository secrets:

```sh
gcloud iam service-accounts keys create github-key.json --iam-account="$DEPLOYER"
gh secret set GCP_CREDENTIALS < github-key.json
rm github-key.json
gh secret set TELEGRAM_BOT_TOKEN
gh secret set GOOGLE_MAPS_API_KEY
python -c 'import secrets; print(secrets.token_urlsafe(32), end="")' | \
  gh secret set TELEGRAM_WEBHOOK_SECRET
gh secret set ALLOWED_USER_IDS
```

Enter the BotFather token, Google Routes API key, and comma-separated numeric Telegram user IDs when prompted. The project ID is read from `GCP_CREDENTIALS`. Application secrets are copied into Google Secret Manager only when the corresponding cloud secret has no enabled version; later deployments do not create duplicate versions.

Treat `GCP_CREDENTIALS` like a password and rotate it immediately if exposed. The provisioning credential is necessarily powerful because a first deployment must enable APIs, create service accounts, and grant their IAM roles. For an established deployment, it can be replaced with a narrower deploy-only identity.

Firestore’s region is permanent. The workflow defaults to London (`europe-west2`); change `REGION` in `.github/workflows/deploy.yml` before the first run if needed.

Cloud Run is publicly reachable because Telegram cannot authenticate with Google IAM. The `/telegram` endpoint still requires Telegram’s secret header, and `/tasks/check` verifies the Cloud Tasks OIDC identity. The `/healthz` endpoint contains no data.

## How estimates behave

The bot queries Google Routes for transit routes arriving by the deadline. Departure is the first boarding time minus the walk to the stop; arrival includes the walk from the final stop. The bot chooses the latest departure among returned routes that meet the deadline. Walking-only routes are supported.

Routes refresh after 200 metres of movement, otherwise every five minutes, or every minute within 30 minutes of departure. Requests are at least 30 seconds apart. While location is fresh, durable checks run every 30 seconds. If location sharing expires, stops, or sends no update for five minutes, the bot warns you and suspends route requests. It then scales back to zero until an alert, deadline, or new webhook. Cached departure alerts still fire and are labelled as based on the last successful estimate.

The bot retains one active trip per allowed chat, including the latest coordinates, route estimate, message ID, task token, and alert state in Firestore. It does not retain location history. `/cancel` and deadline expiry delete the document. Deletion does not remove Telegram messages, data sent to Google, Firestore backups, or provider logs.

This is advisory, not a guarantee. Background app restrictions, Telegram delivery, transit coverage, and schedule changes can affect results. Telegram, Cloud Tasks, and Cloud Run use at-least-once delivery. Current-task tokens and persisted alert levels suppress ordinary duplicates, but a crash after Telegram accepts a message and before Firestore records it can still duplicate a notification.

## Develop and verify

```sh
uv sync --locked
uv run pytest -q
uv run ruff check
uv run ruff format --check
```

Tests use in-memory fakes and do not call Telegram, Google Routes, Firestore, or Cloud Tasks. Before relying on the bot, test a real phone by setting a nearby destination, sharing live location, backgrounding Telegram, and walking for five minutes.

Architecture decisions: [ADR 0001](docs/adr/0001-telegram-transit-bot.md) and [ADR 0002](docs/adr/0002-google-cloud-scale-to-zero.md).
