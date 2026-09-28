from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_github_workflow_only_tests_and_lints() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "uv run pytest -q" in workflow
    assert "uv run ruff check" in workflow
    for forbidden in ("gcloud", "terraform", "id-token: write", "deploy:"):
        assert forbidden not in workflow


def test_single_script_provisions_and_deploys_from_source() -> None:
    script = (ROOT / "deploy.sh").read_text()

    for api in (
        "run.googleapis.com",
        "cloudbuild.googleapis.com",
        "artifactregistry.googleapis.com",
        "firestore.googleapis.com",
        "cloudtasks.googleapis.com",
        "secretmanager.googleapis.com",
        "routes.googleapis.com",
        "apikeys.googleapis.com",
    ):
        assert api in script
    assert "gcloud config get-value project" in script
    assert "gcloud run deploy" in script
    assert "--source=." in script
    assert "python3 scripts/set_webhook.py" in script
    for setting in (
        "--min=0",
        "--max=1",
        "--concurrency=1",
        "--timeout=60s",
        "--memory=512Mi",
        "--cpu-throttling",
        "--cpu-boost",
    ):
        assert setting in script
    for secret in (
        "ALLOWED_USER_IDS=leavenowbot-allowed-user-ids:latest",
        "TELEGRAM_BOT_TOKEN=leavenowbot-telegram-token:latest",
        "GOOGLE_MAPS_API_KEY=leavenowbot-maps-api-key:latest",
        "TELEGRAM_WEBHOOK_SECRET=leavenowbot-webhook-secret:latest",
    ):
        assert secret in script


def test_deploy_preserves_enabled_secrets_and_firestore() -> None:
    script = (ROOT / "deploy.sh").read_text()

    assert "has_enabled_version leavenowbot-telegram-token" in script
    assert "has_enabled_version leavenowbot-maps-api-key" in script
    assert "has_enabled_version leavenowbot-webhook-secret" in script
    assert "has_enabled_version leavenowbot-allowed-user-ids" in script
    assert "gcloud firestore databases describe" in script
    assert "gcloud firestore databases create" in script


def test_deploy_keeps_task_oidc_and_least_privilege_bindings() -> None:
    script = (ROOT / "deploy.sh").read_text()

    assert "roles/run.builder" in script
    assert "roles/datastore.user" in script
    assert "roles/cloudtasks.enqueuer" in script
    assert "roles/iam.serviceAccountUser" in script
    assert "roles/secretmanager.secretAccessor" in script
    assert 'for invoker in allUsers "serviceAccount:${TASKS_SA}"' in script
    assert "TASK_SERVICE_ACCOUNT=${TASKS_SA}" in script


def test_first_install_derives_values_without_plaintext_prompts() -> None:
    script = (ROOT / "deploy.sh").read_text()

    assert 'read -r -s -p "Telegram BotFather token: "' in script
    assert "--api-target=service=routes.googleapis.com" in script
    assert 'call("deleteWebhook", drop_pending_updates="true")' in script
    assert 'call("getUpdates", **values)' in script
    assert "ALLOWED_USER_IDS" in script
