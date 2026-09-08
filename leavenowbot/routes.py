import math
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from leavenowbot.model import Trip


class RouteUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Route:
    leave_at: float
    arrive_at: float
    label: str


def seconds(value: str) -> float:
    if not value.endswith("s"):
        raise ValueError("Invalid duration")
    result = float(value[:-1])
    if not math.isfinite(result) or result < 0:
        raise ValueError("Invalid duration")
    return result


def timestamp(value: str) -> float:
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        raise ValueError("Missing timezone")
    return date.timestamp()


def parse_routes(data: dict, target: float) -> Route:
    candidates = []
    for route in data.get("routes", []):
        try:
            steps = [step for leg in route["legs"] for step in leg["steps"]]
            if not steps:
                continue
            transit = [i for i, step in enumerate(steps) if step["travelMode"] == "TRANSIT"]
            if transit:
                first, last = transit[0], transit[-1]
                before = sum(seconds(s["staticDuration"]) for s in steps[:first])
                after = sum(seconds(s["staticDuration"]) for s in steps[last + 1 :])
                leave = (
                    timestamp(steps[first]["transitDetails"]["stopDetails"]["departureTime"])
                    - before
                )
                arrive = (
                    timestamp(steps[last]["transitDetails"]["stopDetails"]["arrivalTime"]) + after
                )
                names = [
                    steps[i]["transitDetails"].get("transitLine", {}).get("nameShort")
                    or steps[i]["transitDetails"].get("transitLine", {}).get("name", "Transit")
                    for i in transit
                ]
                label = " → ".join(names)[:200]
            elif all(s["travelMode"] == "WALK" for s in steps):
                arrive = target
                leave = target - sum(seconds(s["staticDuration"]) for s in steps)
                label = "Walking"
            else:
                continue
            if leave <= arrive <= target:
                candidates.append(Route(leave, arrive, label))
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    if not candidates:
        raise RouteUnavailable("No usable transit route to meet your arrival target.")
    return max(candidates, key=lambda r: r.leave_at)


class GoogleRoutes:
    def __init__(self, key: str, client: httpx.AsyncClient):
        self.key = key
        self.client = client

    async def calculate(self, trip: Trip) -> Route:
        def waypoint(lat, lon):
            return {"location": {"latLng": {"latitude": lat, "longitude": lon}}}

        try:
            response = await self.client.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                headers={
                    "X-Goog-Api-Key": self.key,
                    "X-Goog-FieldMask": "routes.legs.steps.travelMode,"
                    "routes.legs.steps.staticDuration,routes.legs.steps.transitDetails",
                },
                json={
                    "origin": waypoint(trip.origin_lat, trip.origin_lon),
                    "destination": waypoint(trip.latitude, trip.longitude),
                    "travelMode": "TRANSIT",
                    "arrivalTime": datetime.fromtimestamp(trip.deadline, UTC).isoformat(),
                    "computeAlternativeRoutes": True,
                },
            )
            response.raise_for_status()
            return parse_routes(response.json(), trip.deadline)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            # Provider bodies/URLs may contain sensitive information; never echo them to chat/logs.
            raise RouteUnavailable(
                "Routing service unavailable; check your route manually."
            ) from error
