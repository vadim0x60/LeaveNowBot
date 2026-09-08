import asyncio

import pytest
from telegram.ext import Application

from leavenowbot.app import main


@pytest.mark.parametrize("ids", ["", "alice", "0", "-1", "1,"])
def test_startup_requires_valid_allowlist(monkeypatch, ids):
    monkeypatch.setenv("ALLOWED_USER_IDS", ids)
    with pytest.raises(SystemExit, match="ALLOWED_USER_IDS"):
        main()


def test_startup_requires_keys(monkeypatch):
    monkeypatch.setenv("ALLOWED_USER_IDS", "1")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="required"):
        main()


def test_application_wires_polling_handlers_and_timer(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOWED_USER_IDS", "1,2")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setattr("leavenowbot.app.os.umask", lambda _: None)
    applications = []

    def polling(application, **kwargs):
        assert kwargs == {
            "allowed_updates": ["message", "edited_message"],
            "drop_pending_updates": False,
        }
        assert len(application.handlers[0]) == 3
        assert application.handlers[0][0].commands == {"start", "help", "trip", "status", "cancel"}
        assert len(application.job_queue.jobs()) == 1
        assert application.job_queue.jobs()[0].trigger.interval.total_seconds() == 30
        applications.append(application)

    monkeypatch.setattr(Application, "run_polling", polling)
    main()
    assert len(applications) == 1
    asyncio.run(applications[0].post_shutdown(applications[0]))
