# LeaveNowBot

A personal Telegram bot that tells you when to stop wandering and leave for a destination by public transport.

## Use it

1. Send a **destination pin** using Telegram’s Location attachment (a venue also works).
2. Send the **time to be there**, such as `18:30`.
3. Share your **live location** in the same private chat.

`18:30` means today in `Europe/London` by default. For another day, send `2026-10-01 18:30`; when travelling, you can supply an explicit offset, such as `2026-10-01T18:30+02:00`. The bot confirms the date and timezone. Past times are rejected rather than silently treated as tomorrow. Clock-change ambiguities require an explicit offset.

The bot maintains one status message with the journey, scheduled arrival, leave-by time and estimated wandering budget. It sends separate notifications at **15 minutes or less remaining** and **LEAVE NOW**, with Google Maps and Citymapper links. Each alert level is sent once per trip, even if the route later improves. If the first estimate is already overdue, it sends only the leave-now alert.

- `/trip`: start over with a new destination pin and time.
- `/status`: refresh the existing status message.
- `/cancel`: stop tracking and delete the saved trip and location from the bot’s database.
- `/help` or `/start`: instructions.

There is no flight lookup, calendar integration or automatic safety buffer. The supplied time is the arrival deadline.

## Run it

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

1. Create a bot with Telegram’s [@BotFather](https://t.me/BotFather).
2. Enable Google’s [Routes API](https://developers.google.com/maps/documentation/routes) in a billing-enabled project. Create a server API key restricted to Routes API, and set quotas appropriate to your budget.
3. Copy `.env.example` to `.env`. Set `TELEGRAM_BOT_TOKEN` and `GOOGLE_MAPS_API_KEY`. Set `ALLOWED_USER_IDS` to your numeric Telegram account ID (comma-separated for multiple users), not a username or bot ID. The bot refuses to start without an allowlist and ignores group chats.
4. Run:

```sh
chmod 600 .env
uv sync --locked
uv run --env-file .env leavenowbot
```

`BOT_TIMEZONE` defaults to `Europe/London`; `DATABASE_PATH` defaults to `data/bot.sqlite3`. Run a **single process** with a persistent writable data directory. Do not run another poller for the same token. Long polling needs outbound HTTPS, not a public webhook or inbound port. Use your host’s process supervisor for continuous operation.

The bot retains the active trip, latest coordinates, last route estimate and alert state in SQLite, not a location history. Restarting restores that state. `/cancel` and deadline expiry remove the active record. An unfinished pin/time setup remains until replaced or cancelled. Deletion does not remove messages from Telegram, data sent to Google, or database backups. Avoid debug HTTP logging: Telegram request URLs contain the bot token.

## How estimates behave

Google is asked for transit routes arriving by the deadline. Departure is the first boarding time minus the walk to the stop; arrival includes the walk from the final stop. The bot chooses the latest departure among the returned routes that meet the deadline, not necessarily every possible connection. Walking-only routes returned by Google are supported.

The timer runs every 30 seconds. Routes are refreshed after 200 metres of movement, otherwise every five minutes, or every minute within 30 minutes of departure. Requests are at least 30 seconds apart. Before the first successful route, failures retry at that minimum interval. Avoid setting deadlines months ahead unless you want tracking to run throughout that period.

If location sharing expires, stops, or sends no update for five minutes, the bot warns you and suspends route requests. Static current-location pins work for five minutes. Routing errors also produce a warning. Cached departure alerts still fire, explicitly labelled as based on the last successful estimate. Map buttons open a new directions search; they do not preserve the exact itinerary.

This is an advisory tool, not a guarantee that you will catch a flight or connection. Background app restrictions, Telegram delivery, transit coverage and schedule changes can affect results. A crash after Telegram accepts an alert but before SQLite records it can cause a duplicate notification on restart.

## Verify it

```sh
uv run pytest -q
uv run ruff check
uv run ruff format --check
```

The suite exercises Telegram update parsing, pin/time/location flow, live-message edits, routing requests, timetable calculations, thresholds, errors, authorization and persistence without calling external APIs.

Before relying on the bot, test your phone: set a nearby destination and arrival time, share live location, and walk for five minutes with Telegram backgrounded. Check that “Location updated” advances, that stopping sharing or losing updates produces a warning, and that threshold alerts arrive. Restart the process and verify it resumes the same trip. Real iPhone delivery and live Google responses require your credentials and have not been verified by the automated tests.

Architecture rationale: [ADR 0001](docs/adr/0001-telegram-transit-bot.md).
