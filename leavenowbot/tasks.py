import json
import time
import uuid
from datetime import UTC, datetime

from google.cloud import tasks_v2
from google.protobuf.timestamp_pb2 import Timestamp

from leavenowbot.model import Trip


def next_check_at(trip: Trip, now: float) -> float | None:
    if trip.phase != "tracking":
        return None
    if now >= trip.deadline:
        return now
    if trip.origin_lat is None:
        return min(trip.deadline, now + 29 * 86400)
    if not trip.stale(now):
        return min(trip.deadline, now + 30)

    candidates = [trip.deadline, now + 29 * 86400]
    if trip.leave_at is not None:
        if trip.alert_level < 1 and trip.leave_at - 900 > now:
            candidates.append(trip.leave_at - 900)
        if trip.alert_level < 2 and trip.leave_at > now:
            candidates.append(trip.leave_at)
        elif trip.alert_level < 2:
            candidates.append(now)
    return min(candidates)


class Scheduler:
    def __init__(
        self,
        store,
        client,
        project: str,
        location: str,
        queue: str,
        service_account: str,
    ):
        self.store = store
        self.client = client
        self.parent = client.queue_path(project, location, queue)
        self.service_account = service_account

    async def schedule(self, trip: Trip, task_url: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        check_at = next_check_at(trip, now)
        if check_at is None:
            return

        token = uuid.uuid4().hex
        timestamp = Timestamp()
        timestamp.FromDatetime(datetime.fromtimestamp(max(check_at, now), UTC))
        task = {
            "name": f"{self.parent}/tasks/trip-{trip.chat_id}-{token}",
            "schedule_time": timestamp,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": task_url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"chat_id": trip.chat_id, "token": token}).encode(),
                "oidc_token": {
                    "service_account_email": self.service_account,
                    "audience": task_url,
                },
            },
        }
        await self.client.create_task(parent=self.parent, task=task)
        trip.task_token = token
        await self.store.save(trip)
