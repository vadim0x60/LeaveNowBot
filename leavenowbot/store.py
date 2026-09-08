import json
import sqlite3
from pathlib import Path

from leavenowbot.model import Trip


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS trips (chat_id INTEGER PRIMARY KEY, data TEXT)")

    def get(self, chat_id: int) -> Trip | None:
        row = self.db.execute("SELECT data FROM trips WHERE chat_id = ?", (chat_id,)).fetchone()
        return Trip(**json.loads(row[0])) if row else None

    def all(self) -> list[Trip]:
        return [Trip(**json.loads(row[0])) for row in self.db.execute("SELECT data FROM trips")]

    def save(self, trip: Trip) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO trips VALUES (?, ?)",
                (trip.chat_id, json.dumps(trip.to_dict())),
            )

    def delete(self, chat_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM trips WHERE chat_id = ?", (chat_id,))

    def close(self) -> None:
        self.db.close()
