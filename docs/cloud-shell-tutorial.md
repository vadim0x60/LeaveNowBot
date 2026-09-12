# Deploy LeaveNowBot

This guided setup runs entirely in Google Cloud Shell. Cloud Shell already contains the required tools and uses your logged-in Google identity; it does not create or download a service-account key.

## Select a project

<walkthrough-project-setup billing="true"></walkthrough-project-setup>

Choose a billing-enabled Google Cloud project. The Firestore region is permanent; setup defaults to London (`europe-west2`).

## Provision and deploy

Click **Run in Cloud Shell** below. You will be asked for the Telegram bot token, Google Routes API key, and comma-separated Telegram user IDs. Input is hidden and each value is written directly to Secret Manager. The Telegram webhook secret is generated automatically.

```sh
bash scripts/bootstrap_google_cloud.sh
```

The script is safe to rerun. Existing secret values and infrastructure are retained and reconciled.

## Connect GitHub Actions

At the end, setup prints two non-secret identifiers. Open the repository’s [Actions variables settings](https://github.com/vadim0x60/LeaveNowBot/settings/variables/actions) and create:

* `WIF_PROVIDER`
* `WIF_SERVICE_ACCOUNT`

Copy the corresponding values from the setup output. Future pushes to `master` test and deploy automatically with short-lived Google credentials.

## Finished

The setup has already checked `/healthz` and registered the Telegram webhook. Send `/start` to the bot in Telegram.

<walkthrough-conclusion-trophy></walkthrough-conclusion-trophy>
