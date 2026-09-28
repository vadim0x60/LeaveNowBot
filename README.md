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

You need:

* a billing-enabled Google Cloud project with Owner-equivalent access;
* a Telegram BotFather token; and
* `gcloud`, `curl`, and Python 3 (all are preinstalled in Cloud Shell).

> **Choose the region first:** Firestore’s location is permanent. Deployment defaults to London (`europe-west2`). Set `REGION` on the first run to use another region.

[![Open in Cloud Shell](https://gstatic.com/cloudssh/images/open-btn.svg)](https://shell.cloud.google.com/?cloudshell_git_repo=https%3A%2F%2Fgithub.com%2Fvadim0x60%2FLeaveNowBot&cloudshell_git_branch=master&cloudshell_print=.%2Fdeploy.sh)

Select the project and run the one deployment command:

```sh
gcloud config set project PROJECT_ID
./deploy.sh
```

The script asks only for the BotFather token, with input hidden. It creates a Routes-restricted API key and a random webhook secret. When prompted, send `/start` to the bot; the script reads your numeric user ID from Telegram before registering the webhook. It then provisions the Google Cloud resources, deploys from the existing Dockerfile, checks `/healthz`, and registers the webhook.

Use the same `./deploy.sh` command for updates. Existing Firestore data and enabled Secret Manager values are retained. GitHub Actions runs tests and lint only; it does not deploy.

Cloud Run is publicly reachable because Telegram cannot authenticate with Google IAM. The `/telegram` endpoint still requires Telegram’s secret header, and `/tasks/check` verifies the Cloud Tasks OIDC identity. The `/healthz` endpoint contains no data.

See [deployment details](docs/deployment.md) for region, secret-update, existing-installation, and non-interactive options.

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

Architecture decisions: [ADR 0001](docs/adr/0001-telegram-transit-bot.md), [ADR 0002](docs/adr/0002-google-cloud-scale-to-zero.md), and [ADR 0003](docs/adr/0003-single-command-google-cloud-deployment.md).
