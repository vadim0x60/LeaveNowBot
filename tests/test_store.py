import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from leavenowbot.model import Trip
from leavenowbot.store import Store


def test_firestore_round_trip_uses_chat_document():
    document = SimpleNamespace(get=AsyncMock(), set=AsyncMock(), delete=AsyncMock())
    collection = SimpleNamespace(document=Mock(return_value=document))
    client = SimpleNamespace(collection=Mock(return_value=collection))
    store = Store(client=client)
    trip = Trip(123, phase="tracking", alert_level=1, task_token="current")
    document.get.return_value = SimpleNamespace(exists=True, to_dict=lambda: trip.to_dict())

    async def run():
        assert await store.get(123) == trip
        await store.save(trip)
        await store.delete(123)

    asyncio.run(run())
    client.collection.assert_called_once_with("trips")
    assert collection.document.call_args_list[0].args == ("123",)
    document.set.assert_awaited_once_with(trip.to_dict())
    document.delete.assert_awaited_once()


def test_missing_firestore_document_returns_none():
    document = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(exists=False)),
        set=AsyncMock(),
        delete=AsyncMock(),
    )
    client = SimpleNamespace(
        collection=Mock(return_value=SimpleNamespace(document=Mock(return_value=document)))
    )
    assert asyncio.run(Store(client=client).get(9)) is None
