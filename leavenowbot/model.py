import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass
class Trip:
    chat_id: int
    deadline: float = 0
    latitude: float = 0
    longitude: float = 0
    label: str = "Destination"
    phase: str = "destination"
    origin_lat: float | None = None
    origin_lon: float | None = None
    location_at: float = 0
    location_message_id: int = 0
    live_until: float = 0
    route_lat: float | None = None
    route_lon: float | None = None
    route_at: float = 0
    attempted_at: float = 0
    leave_at: float | None = None
    arrive_at: float | None = None
    route_label: str = ""
    warning: str = ""
    notified_warning: str = ""
    alert_level: int = 0
    status_id: int | None = None
    status_text: str = ""
    task_token: str = ""

    def stale(self, now: float) -> bool:
        return now - self.location_at > 300 or now >= self.live_until

    def to_dict(self) -> dict:
        return asdict(self)


def parse_arrival(text: str, now: datetime, timezone: ZoneInfo) -> float:
    text = text.strip()
    try:
        deadline = (
            datetime.combine(now.astimezone(timezone).date(), time.fromisoformat(text))
            if len(text) == 5
            else datetime.fromisoformat(text)
        )
    except ValueError:
        raise ValueError("Send HH:MM (today), or YYYY-MM-DD HH:MM for another day.") from None
    if deadline.tzinfo is None:
        local = deadline.replace(tzinfo=timezone)
        if (
            local.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) != deadline
            or local.utcoffset() != local.replace(fold=1).utcoffset()
        ):
            raise ValueError("Clock-change time: send a full datetime with a UTC offset.")
        deadline = local
    if not now.timestamp() < deadline.timestamp() <= (now + timedelta(days=100)).timestamp():
        raise ValueError("Arrival must be in the future, within 100 days. HH:MM means today.")
    return deadline.timestamp()


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    h = (
        math.sin((b - a) / 2) ** 2
        + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def route_due(trip: Trip, now: float) -> bool:
    if trip.origin_lat is None or trip.stale(now) or now - trip.attempted_at < 30:
        return False
    if trip.route_lat is None:
        return True
    interval = 60 if trip.leave_at is not None and trip.leave_at - now <= 1800 else 300
    return (
        now - trip.attempted_at >= interval
        or distance_m(trip.origin_lat, trip.origin_lon, trip.route_lat, trip.route_lon) >= 200
    )
