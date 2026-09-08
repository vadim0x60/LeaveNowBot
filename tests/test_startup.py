from zoneinfo import ZoneInfo

import pytest

from leavenowbot.web import Config

REQUIRED = {
    "TELEGRAM_BOT_TOKEN": "123:test-token",
    "GOOGLE_MAPS_API_KEY": "maps-key",
    "TELEGRAM_WEBHOOK_SECRET": "webhook-secret",
    "ALLOWED_USER_IDS": "1,2",
    "GOOGLE_CLOUD_PROJECT": "test-project",
    "TASK_LOCATION": "europe-west2",
    "TASK_QUEUE": "trip-checks",
    "TASK_SERVICE_ACCOUNT": "tasks@test-project.iam.gserviceaccount.com",
}


def set_required(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("ids", ["", "alice", "0", "-1", "1,"])
def test_config_requires_valid_allowlist(monkeypatch, ids):
    set_required(monkeypatch)
    monkeypatch.setenv("ALLOWED_USER_IDS", ids)
    with pytest.raises(RuntimeError, match="ALLOWED_USER_IDS"):
        Config.from_env()


@pytest.mark.parametrize("missing", [name for name in REQUIRED if name != "ALLOWED_USER_IDS"])
def test_config_requires_cloud_runtime_values(monkeypatch, missing):
    set_required(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=missing):
        Config.from_env()


def test_config_reads_cloud_runtime(monkeypatch):
    set_required(monkeypatch)
    config = Config.from_env()
    assert config.allowed == {1, 2}
    assert config.timezone == ZoneInfo("Europe/London")
    assert config.project == "test-project"
