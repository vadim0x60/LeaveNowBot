# ADR 0003: Single-command Google Cloud deployment

Status: Accepted

## Context

ADR 0002 selected Google Cloud's scale-to-zero services and specified Terraform, Cloud Build, and separate build identities. The later deployment implementation added two Terraform stacks, remote state, GitHub Actions deployment, and Workload Identity Federation. Although declarative, that path required several tools and a multi-stage handoff between Cloud Shell, Google Cloud, and GitHub. The owner attempted the documented flow and it did not provide a dependable no-fuss installation.

The application still requires Google Routes, and remaining on Google Cloud is a settled constraint. A new installation has only two necessary human inputs: the billing-enabled Google Cloud project and the BotFather token. The Routes key, webhook secret, and Telegram user ID can be derived or generated.

## Decision

Use one idempotent `./deploy.sh` for first installation and every update. It reads the selected project from `gcloud`, provisions missing Google Cloud resources and IAM bindings with `gcloud`, stores generated or discovered values in Secret Manager, and deploys the existing Dockerfile through `gcloud run deploy --source .`. Source deployment uses the Compute Engine default service account with the Cloud Run Builder role instead of a project-specific build account. The script verifies the health endpoint and then registers the Telegram webhook.

The script preserves an existing Firestore database and enabled secret versions. Before the first webhook registration, it removes any old webhook and obtains the allowlisted user ID from a `/start` update. It creates a Routes-restricted API key and generates the webhook secret. An environment variable supports non-interactive or multi-user allowlists.

GitHub Actions runs tests and lint but does not deploy. Terraform state, a state bucket, deployment-time Workload Identity Federation, and push-to-production automation are no longer part of the supported deployment path.

## Consequences

Installation and updates use one tool and one command, with no credentials copied into GitHub. The flow works in Cloud Shell or anywhere an authenticated `gcloud` is installed. Existing installations can adopt it without replacing Firestore data or secret values.

We trade away declarative infrastructure plans, drift reconciliation, and push-to-deploy. The script creates resources and required bindings only when absent, while each Cloud Run deployment explicitly reapplies runtime settings. Operators run the command manually for releases and update secrets directly in Secret Manager. Firestore's location remains a permanent first-run choice.
