import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from leavenowbot.model import Trip
from leavenowbot.routes import GoogleRoutes, RouteUnavailable, parse_routes


def at(time):
    return datetime.fromisoformat(f"2026-09-08T{time}:00+00:00").timestamp()


def walk(duration):
    return {"travelMode": "WALK", "staticDuration": f"{duration}s"}


def train(departure, arrival, name="Express"):
    return {
        "travelMode": "TRANSIT",
        "transitDetails": {
            "stopDetails": {
                "departureTime": f"2026-09-08T{departure}:00Z",
                "arrivalTime": f"2026-09-08T{arrival}:00Z",
            },
            "transitLine": {"nameShort": name},
        },
    }


def itinerary(*steps):
    return {"legs": [{"steps": list(steps)}]}


def test_schedule_uses_boarding_minus_walk_not_deadline_minus_duration():
    data = {"routes": [itinerary(walk(420), train("16:20", "17:02"), walk(180))]}
    route = parse_routes(data, at("17:30"))
    assert route.leave_at == at("16:13")
    assert route.arrive_at == at("17:05")
    assert route.label == "Express"


def test_latest_feasible_alternative_includes_final_walk_and_transfers():
    data = {
        "routes": [
            itinerary(walk(420), train("16:20", "17:02"), walk(180)),
            itinerary(
                walk(120),
                train("16:30", "17:04", "A"),
                walk(60),
                train("17:10", "17:20", "B"),
                walk(240),
            ),
            itinerary(walk(60), train("16:50", "17:28"), walk(180)),  # too late after walk
        ]
    }
    route = parse_routes(data, at("17:30"))
    assert route.leave_at == at("16:28")
    assert route.arrive_at == at("17:24")
    assert route.label == "A → B"


def test_all_walking_and_fractional_duration():
    route = parse_routes({"routes": [itinerary(walk(61.5), walk(180))]}, at("17:30"))
    assert route.leave_at == at("17:30") - 241.5
    assert route.arrive_at == at("17:30")


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"routes": []},
        {"routes": [{}]},
        {"routes": [itinerary({"travelMode": "TRANSIT"})]},
        {"routes": [itinerary(walk(-1))]},
        {"routes": [itinerary(train("17:45", "18:00"))]},
    ],
)
def test_unusable_routes_do_not_produce_reassuring_estimate(data):
    with pytest.raises(RouteUnavailable):
        parse_routes(data, at("17:30"))


def test_google_request_contract():
    def respond(request):
        assert request.url.path == "/directions/v2:computeRoutes"
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        assert "staticDuration" in request.headers["X-Goog-FieldMask"]
        body = json.loads(request.content)
        assert body["origin"]["location"]["latLng"] == {"latitude": 51.5, "longitude": -0.12}
        assert body["destination"]["location"]["latLng"] == {"latitude": 51.47, "longitude": -0.45}
        assert body["travelMode"] == "TRANSIT"
        assert "departureTime" not in body
        assert datetime.fromisoformat(body["arrivalTime"]) == datetime(
            2026, 9, 8, 17, 30, tzinfo=UTC
        )
        return httpx.Response(200, json={"routes": [itinerary(walk(180))]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            route = await GoogleRoutes("test-key", client).calculate(
                Trip(
                    1,
                    at("17:30"),
                    51.47,
                    -0.45,
                    origin_lat=51.5,
                    origin_lon=-0.12,
                )
            )
            assert route.leave_at == at("17:27")

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["quota", "timeout", "invalid-json"])
def test_provider_errors_are_redacted(failure):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive coordinates", request=request)
        if failure == "invalid-json":
            return httpx.Response(200, text="sensitive coordinates")
        return httpx.Response(429, text="sensitive coordinates")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(RouteUnavailable, match="service unavailable") as caught:
                await GoogleRoutes("secret", client).calculate(Trip(1, at("17:30")))
            assert "sensitive" not in str(caught.value)
            assert "secret" not in str(caught.value)

    asyncio.run(run())
