# Google Cloud deployment

## Browser-first setup

The [Open in Cloud Shell setup](../README.md#deploy-to-google-cloud) is the primary deployment path. It requires a billing-enabled Google Cloud project and Owner-equivalent access, but no locally installed tools. Cloud Shell is a Google-hosted browser session with `gcloud`, Terraform, Git, and Docker already available and authenticated as the signed-in user.

The guided setup automates initial provisioning:

* **Infrastructure and state:** It creates the versioned `${PROJECT_ID}-leavenowbot-tfstate` bucket and applies `infra/bootstrap` and `infra/app` as the signed-in project owner.
* **Application values:** It prompts for the Telegram token, Routes API key, and allowed Telegram user IDs without echoing them. It writes each value directly to Secret Manager only when no enabled version exists and generates the Telegram webhook secret.
* **Deployment:** It builds the image, verifies `/healthz`, registers the webhook, and prints the two non-secret GitHub variables needed for continuous deployment.

The setup is idempotent. A rerun uses the same state and reconciles the same resources.

To choose another Firestore region, set `REGION` for the setup command in Cloud Shell and change the workflow’s `REGION` value before the first run. Both values must continue to match. To deploy a fork, set `GITHUB_REPOSITORY` to its `owner/name`. The repository value is included in the Workload Identity Provider condition and must match the repository running the workflow.

## Continuous deployment

Store the bootstrap outputs under **GitHub → Settings → Secrets and variables → Actions → Variables**:

| Variable | Value |
| --- | --- |
| `WIF_PROVIDER` | Full Workload Identity Provider resource name |
| `WIF_SERVICE_ACCOUNT` | `leavenowbot-github@PROJECT_ID.iam.gserviceaccount.com` |

These values are identifiers, not credentials. The workflow requests `id-token: write`, exchanges GitHub’s OIDC token through the provider, and impersonates the dedicated deployment service account. The provider accepts only GitHub tokens for the configured repository and `refs/heads/master`. The Cloud Run service uses the separate `leavenowbot-runtime` identity.

Pushes to `master` then run tests, update infrastructure, build an immutable image, deploy the Cloud Run revision, check `/healthz`, and register the webhook. No application value is stored in or passed through GitHub.

## Existing deployment migration

The browser setup also migrates an installation created by the old key-based workflow:

1. Open the setup and select the existing project. **Do not choose another region.**
2. Run setup. Existing Terraform state, Firestore, and Secret Manager versions are retained; only the allowed-user IDs value is requested if it does not yet exist in Secret Manager.
3. Add `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` as GitHub repository variables.
4. Run the workflow from `master` and confirm it succeeds.
5. In GitHub repository settings, remove the obsolete application and Google credential secrets.
6. In Google Cloud IAM, disable the old deployment service-account key, verify another deployment, and then delete that key.

Terraform configures Firestore with deletion protection and an `ABANDON` deletion policy. Migration updates the Cloud Run revision to read allowed-user IDs from Secret Manager; it does not recreate Firestore.

## Updating application values

Add a new enabled version in Google Secret Manager, then rerun the deployment workflow so Cloud Run creates a revision resolving `latest`. The four secret names are:

* `leavenowbot-telegram-token`
* `leavenowbot-maps-api-key`
* `leavenowbot-webhook-secret`
* `leavenowbot-allowed-user-ids`

Do not place these values in GitHub. If the Telegram token or webhook secret changes, the deployment workflow re-registers the webhook after the health check.
