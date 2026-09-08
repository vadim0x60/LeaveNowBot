from google.cloud import firestore

from leavenowbot.model import Trip


class Store:
    """Firestore-backed trip storage.

    Cloud Run is configured for one concurrent request, so each document can retain
    the simple read/change/write state machine used by the bot.
    """

    def __init__(self, project: str | None = None, client=None):
        self.client = client or firestore.AsyncClient(project=project)
        self.trips = self.client.collection("trips")

    async def get(self, chat_id: int) -> Trip | None:
        snapshot = await self.trips.document(str(chat_id)).get()
        return Trip(**snapshot.to_dict()) if snapshot.exists else None

    async def save(self, trip: Trip) -> None:
        await self.trips.document(str(trip.chat_id)).set(trip.to_dict())

    async def delete(self, chat_id: int) -> None:
        await self.trips.document(str(chat_id)).delete()
