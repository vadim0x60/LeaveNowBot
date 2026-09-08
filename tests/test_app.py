import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError
from telegram.ext import MessageHandler, filters

from leavenowbot.app import Bot, links
from leavenowbot.model import Trip
from leavenowbot.routes import Route, RouteUnavailable
from leavenowbot.store import Store


@pytest.fixture
def rig(tmp_path):
    store = Store(str(tmp_path / "state.sqlite3"))
    api = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=100)),
        edit_message_text=AsyncMock(),
    )
    routes = SimpleNamespace(calculate=AsyncMock())
    bot = Bot(store, routes, {1}, ZoneInfo("Europe/London"))
    yield bot, routes, api, SimpleNamespace(bot=api)
    store.close()


def update(api, message_id=1, user=1, edited=False, chat_type="private", **fields):
    data = {
        "message_id": message_id,
        "date": int(time.time()),
        "chat": {"id": user, "type": chat_type},
        "from": {"id": user, "is_bot": False, "first_name": "Test"},
        **fields,
    }
    return Update.de_json(
        {"update_id": message_id, "edited_message" if edited else "message": data}, api
    )


def messages(api):
    return [
        call.args[1] if len(call.args) > 1 else call.kwargs["text"]
        for call in api.send_message.call_args_list
    ]


def active(now, **kwargs):
    return Trip(
        1,
        deadline=now + 7200,
        phase="tracking",
        origin_lat=51.5,
        origin_lon=-0.12,
        latitude=51.47,
        longitude=-0.45,
        location_at=now,
        live_until=now + 3600,
        **kwargs,
    )


def test_pin_time_live_location_edit_and_cancel(rig):
    bot, routes, api, context = rig
    now = time.time()
    routes.calculate.return_value = Route(now + 2400, now + 5400, "Train")

    async def run():
        pin = update(api, location={"latitude": 51.47, "longitude": -0.45})
        await bot.location(pin, context)
        assert bot.store.get(1).phase == "time"
        assert "Europe/London" in messages(api)[-1]
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%d 18:30")
        await bot.arrival(update(api, 2, text=tomorrow), context)
        assert bot.store.get(1).phase == "tracking"
        assert "Waiting for your location" in messages(api)[-1]
        live = update(api, 3, location={"latitude": 51.5, "longitude": -0.12, "live_period": 3600})
        await bot.location(live, context)
        assert routes.calculate.await_count == 1
        assert bot.store.get(1).latitude == 51.47  # Destination wasn't overwritten by origin.
        assert bot.store.get(1).origin_lat == 51.5
        edited = update(
            api,
            3,
            edited=True,
            edit_date=int(now) + 1,
            location={"latitude": 51.501, "longitude": -0.12, "live_period": 3600},
        )
        assert MessageHandler(filters.LOCATION, bot.location).check_update(edited)
        await bot.location(edited, context)
        assert bot.store.get(1).origin_lat == 51.501
        assert routes.calculate.await_count == 1  # GPS changes don't hammer Google.
        await bot.command(update(api, 4, text="/cancel"), context)
        assert bot.store.get(1) is None
        await bot.location(edited, context)  # Late edits cannot recreate cancelled tracking.
        assert bot.store.get(1) is None

    asyncio.run(run())


@pytest.mark.parametrize("user,chat_type", [(2, "private"), (1, "group")])
def test_unauthorized_users_and_groups_are_ignored(rig, user, chat_type):
    bot, routes, api, context = rig

    async def run():
        await bot.location(
            update(api, user=user, chat_type=chat_type, location={"latitude": 1, "longitude": 2}),
            context,
        )
        await bot.command(update(api, user=user, chat_type=chat_type, text="/trip"), context)
        await bot.arrival(update(api, user=user, chat_type=chat_type, text="18:30"), context)

    asyncio.run(run())
    assert not bot.store.all()
    api.send_message.assert_not_awaited()
    routes.calculate.assert_not_awaited()


def test_venue_pin_and_invalid_time_leave_draft_intact(rig):
    bot, routes, api, context = rig

    async def run():
        await bot.location(
            update(
                api,
                venue={
                    "title": "Station",
                    "address": "Road",
                    "location": {"latitude": 51, "longitude": 0},
                },
            ),
            context,
        )
        await bot.arrival(update(api, 2, text="not a time"), context)

    asyncio.run(run())
    trip = bot.store.get(1)
    assert trip.phase == "time" and trip.label == "Station"
    routes.calculate.assert_not_awaited()


def test_old_live_sessions_and_out_of_order_edits_are_ignored(rig):
    bot, _, api, context = rig
    now = time.time()
    bot.store.save(active(now, location_message_id=10, attempted_at=now))

    async def run():
        for message_id, edit_date in [(9, int(now) + 1), (10, int(now) - 1)]:
            await bot.location(
                update(
                    api,
                    message_id,
                    edited=True,
                    edit_date=edit_date,
                    location={"latitude": 0, "longitude": 0, "live_period": 3600},
                ),
                context,
            )

    asyncio.run(run())
    assert bot.store.get(1).origin_lat == 51.5
    api.send_message.assert_not_awaited()


def test_thresholds_are_inclusive_and_not_repeated_after_reload(rig):
    bot, routes, api, _ = rig
    now = time.time()
    trip = active(
        now,
        leave_at=now + 901,
        arrive_at=now + 3000,
        attempted_at=now,
        route_lat=51.5,
        route_lon=-0.12,
        route_at=now,
    )

    async def run():
        await bot.refresh(api, trip, now)
        assert not any(t.startswith("🟡") for t in messages(api))
        await bot.refresh(api, trip, now + 1)
        assert sum(t.startswith("🟡") for t in messages(api)) == 1
        await bot.refresh(api, bot.store.get(1), now + 2)
        await bot.refresh(api, bot.store.get(1), now + 901)
        await bot.refresh(api, bot.store.get(1), now + 930)

    asyncio.run(run())
    assert sum(t.startswith("🟡") for t in messages(api)) == 1
    assert sum(t.startswith("🔴 LEAVE NOW") for t in messages(api)) == 1
    assert bot.store.get(1).alert_level == 2
    assert api.edit_message_text.await_count >= 2
    # Stale GPS; deadline alert still fires from cached route.
    routes.calculate.assert_not_awaited()


def test_timer_reroutes_when_stationary(rig, monkeypatch):
    bot, routes, api, context = rig
    now = time.time()
    trip = active(
        now,
        attempted_at=now - 60,
        route_at=now - 60,
        route_lat=51.5,
        route_lon=-0.12,
        leave_at=now + 1800,
        arrive_at=now + 4000,
    )
    bot.store.save(trip)
    routes.calculate.return_value = Route(now + 600, now + 4000, "Earlier train")
    monkeypatch.setattr("leavenowbot.app.time.time", lambda: now)
    asyncio.run(bot.tick(context))
    routes.calculate.assert_awaited_once()
    assert bot.store.get(1).leave_at == now + 600
    assert any(t.startswith("🟡") for t in messages(api))


def test_route_failure_warns_once_and_recovers(rig):
    bot, routes, api, _ = rig
    now = time.time()
    trip = active(now)
    routes.calculate.side_effect = RouteUnavailable("No usable route")

    async def run():
        await bot.refresh(api, trip, now)
        await bot.refresh(api, trip, now + 30)
        assert sum(t.startswith("⚠️") for t in messages(api)) == 1
        assert "Wandering budget" not in trip.status_text
        routes.calculate.side_effect = None
        routes.calculate.return_value = Route(now + 3600, now + 6000, "Recovered")
        await bot.refresh(api, trip, now + 60)
        assert trip.warning == trip.notified_warning == ""
        assert "Wandering budget" in trip.status_text

    asyncio.run(run())


@pytest.mark.parametrize("period", [None, 2147483647])
@pytest.mark.parametrize("timedelta_mode", ["true", "false"])
def test_stopped_and_indefinite_live_location(rig, period, timedelta_mode, monkeypatch):
    monkeypatch.setenv("PTB_TIMEDELTA", timedelta_mode)
    bot, _, api, context = rig
    now = int(time.time())
    bot.store.save(active(now, attempted_at=now, location_message_id=10))
    location = {"latitude": 51.5, "longitude": -0.12}
    if period:
        location["live_period"] = period
    asyncio.run(
        bot.location(update(api, 10, edited=True, edit_date=now, location=location), context)
    )
    trip = bot.store.get(1)
    assert trip.stale(now) == (period is None)


def test_deleted_status_is_recreated_and_failed_alert_is_retried(rig):
    bot, _, api, _ = rig
    now = time.time()
    trip = active(now, status_id=42, attempted_at=now, leave_at=now, arrive_at=now + 3000)

    async def run():
        api.send_message.side_effect = NetworkError("offline")
        with pytest.raises(NetworkError):
            await bot.refresh(api, trip, now)
        assert bot.store.get(1).alert_level == 0
        api.send_message.side_effect = None
        api.edit_message_text.side_effect = BadRequest("Message to edit not found")
        await bot.refresh(api, bot.store.get(1), now)
        assert bot.store.get(1).status_id == 100
        assert bot.store.get(1).alert_level == 2

    asyncio.run(run())


def test_blocked_user_is_removed_without_stopping_other_users(rig):
    bot, _, api, context = rig
    bot.store.save(active(time.time(), attempted_at=time.time()))
    api.send_message.side_effect = Forbidden("blocked")
    asyncio.run(bot.tick(context))
    assert bot.store.get(1) is None


@pytest.mark.parametrize("offline", [False, True])
def test_expired_trip_is_removed(rig, offline):
    bot, routes, api, _ = rig
    now = time.time()
    trip = active(now)
    bot.store.save(trip)
    if offline:
        api.send_message.side_effect = NetworkError("offline")
        with pytest.raises(NetworkError):
            asyncio.run(bot.refresh(api, trip, trip.deadline))
    else:
        asyncio.run(bot.refresh(api, trip, trip.deadline))
    assert bot.store.get(1) is None
    routes.calculate.assert_not_awaited()


def test_map_buttons_encode_asymmetric_origin_and_destination():
    keyboard = links(
        Trip(1, latitude=51.47, longitude=-0.45, origin_lat=51.52, origin_lon=-0.12, label="A & B")
    )
    google, city = keyboard.inline_keyboard[0]
    assert google.text == "Google Maps" and city.text == "Citymapper"
    assert parse_qs(urlparse(google.url).query)["origin"] == ["51.52,-0.12"]
    assert parse_qs(urlparse(google.url).query)["destination"] == ["51.47,-0.45"]
    assert parse_qs(urlparse(city.url).query)["endname"] == ["A & B"]
