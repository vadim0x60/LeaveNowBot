import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from leavenowbot.model import Trip
from leavenowbot.tasks import Scheduler, next_check_at


def tracking(now, **values):
    return Trip(
        1,
        phase="tracking",
        deadline=now + 7200,
        origin_lat=51.5,
        origin_lon=-0.1,
        location_at=now,
        live_until=now + 3600,
        **values,
    )


def test_next_check_keeps_fresh_tracking_active_then_sleeps_when_stale():
    now = 1_000_000
    trip = tracking(now)
    assert next_check_at(trip, now) == now + 30
    trip.location_at = now - 301
    trip.live_until = now - 1
    trip.leave_at = now + 1800
    assert next_check_at(trip, now) == now + 900
    trip.alert_level = 1
    assert next_check_at(trip, now) == now + 1800


def test_next_check_waits_for_webhook_or_deadline_without_location():
    now = 1_000_000
    trip = tracking(now)
    trip.origin_lat = trip.origin_lon = None
    assert next_check_at(trip, now) == trip.deadline
    trip.phase = "time"
    assert next_check_at(trip, now) is None


def test_scheduler_creates_oidc_task_before_persisting_its_token():
    now = 1_000_000
    calls = []

    class Store:
        async def save(self, trip):
            calls.append(("save", trip.task_token))

    client = SimpleNamespace(
        queue_path=lambda project, location, queue: f"{project}/{location}/{queue}",
        create_task=AsyncMock(side_effect=lambda **kwargs: calls.append(("task", kwargs))),
    )
    trip = tracking(now)
    scheduler = Scheduler(Store(), client, "project", "region", "queue", "tasks@example.com")
    asyncio.run(scheduler.schedule(trip, "https://service/tasks/check", now))

    assert [kind for kind, _ in calls] == ["task", "save"]
    task = calls[0][1]["task"]
    assert task["http_request"]["oidc_token"] == {
        "service_account_email": "tasks@example.com",
        "audience": "https://service/tasks/check",
    }
    assert trip.task_token.encode() in task["http_request"]["body"]
