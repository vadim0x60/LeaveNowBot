import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx

from leavenowbot.model import Trip
from leavenowbot.web import Config, create_app


class MemoryStore:
    def __init__(self, trip=None):
        self.data = {trip.chat_id: trip} if trip else {}

    async def get(self, chat_id):
        trip = self.data.get(chat_id)
        return Trip(**trip.to_dict()) if trip else None

    async def save(self, trip):
        self.data[trip.chat_id] = Trip(**trip.to_dict())

    async def delete(self, chat_id):
        self.data.pop(chat_id, None)


def config():
    return Config(
        token="123:test-token",
        maps_key="maps-key",
        webhook_secret="telegram-secret",
        allowed={1},
        timezone=ZoneInfo("Europe/London"),
        project="project",
        task_location="region",
        task_queue="queue",
        task_service_account="tasks@example.com",
    )


def update_payload():
    return {
        "update_id": 10,
        "message": {
            "message_id": 20,
            "date": int(time.time()),
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "photo": [
                {
                    "file_id": "file-id",
                    "file_unique_id": "unique-id",
                    "width": 1,
                    "height": 1,
                }
            ],
        },
    }


def rig(trip=None, verifier=None):
    store = MemoryStore(trip)
    tasks = SimpleNamespace(
        queue_path=lambda project, location, queue: f"{project}/{location}/{queue}",
        create_task=AsyncMock(),
    )
    app = create_app(
        config(),
        store=store,
        routes=SimpleNamespace(calculate=AsyncMock()),
        tasks_client=tasks,
        task_verifier=verifier or AsyncMock(return_value=True),
    )
    # ASGITransport does not run lifespan; no Telegram API call is needed by these requests.
    app.state.telegram._initialized = True
    return app, store, tasks


def test_webhook_requires_telegram_secret_and_schedules_active_trip():
    now = time.time()
    trip = Trip(1, phase="tracking", deadline=now + 3600)
    app, store, tasks = rig(trip)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://bot.example") as client:
            denied = await client.post("/telegram", json=update_payload())
            accepted = await client.post(
                "/telegram",
                json=update_payload(),
                headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"},
            )
        assert denied.status_code == 403
        assert accepted.status_code == 204

    asyncio.run(run())
    tasks.create_task.assert_awaited_once()
    assert store.data[1].task_token
    request = tasks.create_task.await_args.kwargs["task"]["http_request"]
    assert request["url"] == "https://bot.example/tasks/check"


def test_task_authentication_and_current_token_gate_execution():
    now = time.time()
    trip = Trip(1, phase="tracking", deadline=now + 3600, task_token="current")
    verifier = AsyncMock(side_effect=[False, True, True])
    app, store, tasks = rig(trip, verifier)
    app.state.bot.tick = AsyncMock()

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://bot.example") as client:
            denied = await client.post("/tasks/check", json={"chat_id": 1, "token": "current"})
            stale = await client.post("/tasks/check", json={"chat_id": 1, "token": "old"})
            accepted = await client.post("/tasks/check", json={"chat_id": 1, "token": "current"})
        assert denied.status_code == 403
        assert stale.status_code == 204
        assert accepted.status_code == 204

    asyncio.run(run())
    app.state.bot.tick.assert_awaited_once_with(app.state.telegram.bot, 1)
    tasks.create_task.assert_awaited_once()
    assert store.data[1].task_token != "current"
    body = tasks.create_task.await_args.kwargs["task"]["http_request"]["body"]
    assert json.loads(body)["token"] == store.data[1].task_token
