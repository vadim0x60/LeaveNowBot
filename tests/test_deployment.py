from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_deploy_uses_federated_identity_without_application_secrets() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()

    assert "id-token: write" in workflow
    assert "workload_identity_provider: ${{ vars.WIF_PROVIDER }}" in workflow
    assert "service_account: ${{ vars.WIF_SERVICE_ACCOUNT }}" in workflow
    for forbidden in ("secrets.", "credentials" + "_json"):
        assert forbidden not in workflow


def test_github_federation_is_repository_and_branch_scoped() -> None:
    bootstrap = (ROOT / "infra/bootstrap/main.tf").read_text()

    condition = (
        "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/master'"
    )
    assert condition in bootstrap
    assert "roles/iam.workloadIdentityUser" in bootstrap


def test_runtime_configuration_comes_from_secret_manager() -> None:
    app = (ROOT / "infra/app/main.tf").read_text()
    bootstrap = (ROOT / "infra/bootstrap/main.tf").read_text()

    assert 'secret  = "leavenowbot-allowed-user-ids"' in app
    assert '"allowed-user-ids"' in bootstrap


def test_bootstrap_adopts_the_legacy_deployer_account() -> None:
    script = (ROOT / "scripts/bootstrap_google_cloud.sh").read_text()

    assert "state show google_service_account.deployer" in script
    assert "terraform -chdir=infra/bootstrap import" in script
