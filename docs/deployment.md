# Google Cloud deployment

## Deploy or update

Use [Open in Cloud Shell](../README.md#deploy-to-google-cloud), or clone the repository anywhere `gcloud`, Python 3, and `curl` are installed. Authenticate with an account that can administer the project, select a billing-enabled project, and run:

```sh
gcloud config set project PROJECT_ID
./deploy.sh
```

`deploy.sh` is both the installer and updater. It enables APIs, creates missing resources and IAM bindings, builds from the Dockerfile with Cloud Build, deploys Cloud Run, checks `/healthz`, and registers the Telegram webhook. Reruns retain Firestore data and every secret that already has an enabled version.

The default region is `europe-west2`. Firestore's location is permanent, so choose before the first run:

```sh
REGION=europe-west1 ./deploy.sh
```

Continue setting the same `REGION` on later runs. The script refuses to proceed if it differs from an existing Firestore database. `BOT_TIMEZONE` can likewise override the default `Europe/London` application timezone.

On a first install, the only typed value is the hidden BotFather token. The script creates and stores a Routes-only API key and random webhook secret. It removes any existing Telegram webhook, asks you to send `/start`, and obtains your numeric ID through `getUpdates` before installing the new webhook. For a non-interactive or multi-user setup, provide comma-separated IDs:

```sh
ALLOWED_USER_IDS=123456789,987654321 ./deploy.sh
```

## Existing installations

Select the existing project and use its original region. Running `./deploy.sh` does not apply or destroy the old Terraform state, Firestore database, state bucket, Workload Identity resources, or deployer account. Those unused resources can be removed separately after a successful deployment, but removal is not required. Existing enabled values under these names are reused:

* `leavenowbot-telegram-token`
* `leavenowbot-maps-api-key`
* `leavenowbot-webhook-secret`
* `leavenowbot-allowed-user-ids`

GitHub no longer deploys production. The repository workflow only runs tests and lint, so WIF GitHub variables are no longer needed.

## Update a secret

Add a new enabled Secret Manager version, then rerun `./deploy.sh` so Cloud Run creates a revision resolving `latest`. For example:

```sh
printf '%s' 'NEW_VALUE' | gcloud secrets versions add leavenowbot-allowed-user-ids --data-file=-
./deploy.sh
```

Use the same command with the appropriate secret name from the list above. Do not put application values in GitHub. If the Telegram token or webhook secret changes, the redeploy registers the webhook with the new value.

To rotate the Maps key while retaining its Routes API restriction, create a replacement with `gcloud services api-keys create --api-target=service=routes.googleapis.com`, store the result as a new `leavenowbot-maps-api-key` version, and redeploy.
