from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from leavenowbot.model import Trip, distance_m, parse_arrival, route_due
from leavenowbot.store import Store

LONDON = ZoneInfo("Europe/London")


def test_arrival_today_uses_london_not_utc():
    now = datetime(2026, 9, 8, 12, tzinfo=UTC)
    assert (
        parse_arrival("18:30", now, LONDON) == datetime(2026, 9, 8, 17, 30, tzinfo=UTC).timestamp()
    )
    assert (
        parse_arrival("2026-09-09 18:30", now, LONDON)
        == datetime(2026, 9, 9, 17, 30, tzinfo=UTC).timestamp()
    )
    assert (
        parse_arrival("2026-09-09T18:30+02:00", now, LONDON)
        == datetime(2026, 9, 9, 16, 30, tzinfo=UTC).timestamp()
    )


def test_today_uses_local_date_near_midnight():
    now = datetime(2026, 9, 8, 23, 10, tzinfo=UTC)
    assert (
        parse_arrival("00:30", now, LONDON) == datetime(2026, 9, 8, 23, 30, tzinfo=UTC).timestamp()
    )


@pytest.mark.parametrize("text", ["12:00", "13:00", "25:00", "tomorrow", "2027-09-01 18:00"])
def test_bad_or_elapsed_time_is_rejected_not_shifted_to_tomorrow(text):
    with pytest.raises(ValueError):
        parse_arrival(text, datetime(2026, 9, 8, 12, tzinfo=UTC), LONDON)


@pytest.mark.parametrize("date", ["2026-03-29", "2026-10-25"])
def test_dst_gap_and_fold_require_explicit_offset(date):
    now = datetime.fromisoformat(date).replace(tzinfo=UTC)
    with pytest.raises(ValueError, match="Clock-change"):
        parse_arrival(f"{date} 01:30", now, LONDON)
    assert parse_arrival(f"{date}T01:30+00:00", now, LONDON) == now.timestamp() + 5400


def test_routing_cadence_and_movement_boundaries():
    trip = Trip(1, origin_lat=51, origin_lon=0, location_at=1000, live_until=10000)
    assert route_due(trip, 1000)
    trip.attempted_at = 1000
    trip.route_lat, trip.route_lon = 51, 0
    assert not route_due(trip, 1299)
    assert route_due(trip, 1300)
    trip.leave_at = 2000
    assert not route_due(trip, 1059)
    assert route_due(trip, 1060)
    trip.origin_lat = 51.003  # >200 m; trigger sooner, but never within 30 seconds.
    assert not route_due(trip, 1029)
    assert route_due(trip, 1030)
    trip.origin_lat = 51.001  # <200 m
    assert not route_due(trip, 1030)
    assert not route_due(trip, 1301)  # stale location
    trip.live_until = 1030
    assert not route_due(trip, 1030)  # expired sharing, despite fresh coordinates
    assert 333 < distance_m(51, 0, 51.003, 0) < 334


def test_store_survives_restart_and_isolates_users(tmp_path):
    path = str(tmp_path / "state.sqlite3")
    store = Store(path)
    trip = Trip(1, phase="tracking", origin_lat=51.5, origin_lon=-0.12, alert_level=1, status_id=42)
    store.save(trip)
    store.save(Trip(2, phase="time"))
    store.close()
    store = Store(path)
    assert store.get(1) == trip
    store.delete(1)
    assert store.get(1) is None
    assert [t.chat_id for t in store.all()] == [2]
    store.close()
