import asyncio
import logging
import math
import os
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from leavenowbot.model import Trip, parse_arrival, route_due
from leavenowbot.routes import GoogleRoutes, RouteUnavailable
from leavenowbot.store import Store

LOG = logging.getLogger(__name__)
HELP = """1. Send a destination pin (attachment → Location → choose a place).
2. Send the time to be there, e.g. 18:30. I'll confirm the date and timezone.
3. Share your LIVE location so I can calculate when you need to leave.

HH:MM means today. For another day, send YYYY-MM-DD HH:MM.
You can also send a full datetime with an offset, e.g. 2026-10-01T18:30+02:00.
A static location works too, but must be refreshed within five minutes.

/trip — start over with a new destination
/status — show the current estimate
/cancel — stop tracking and delete your saved trip and location
/help — show this help

Transit only. No automatic buffer. Estimates are not guarantees; check the linked route.
Live-location updates depend on your phone and Telegram; this bot cannot request GPS silently."""


def links(trip: Trip) -> InlineKeyboardMarkup:
    destination = f"{trip.latitude},{trip.longitude}"
    google = {"api": 1, "destination": destination, "travelmode": "transit"}
    city = {"endcoord": destination, "endname": trip.label}
    if trip.origin_lat is not None:
        origin = f"{trip.origin_lat},{trip.origin_lon}"
        google["origin"] = origin
        city["startcoord"] = origin
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Google Maps", url="https://www.google.com/maps/dir/?" + urlencode(google)
                ),
                InlineKeyboardButton(
                    "Citymapper", url="https://citymapper.com/directions?" + urlencode(city)
                ),
            ]
        ]
    )


class Bot:
    def __init__(self, store: Store, routes: GoogleRoutes, allowed: set[int], timezone: ZoneInfo):
        self.store, self.routes, self.allowed, self.timezone = store, routes, allowed, timezone
        # Serialize timer and message updates so stale snapshots cannot overwrite /cancel or GPS.
        self.lock = asyncio.Lock()

    def authorized(self, update: Update) -> bool:
        return bool(
            update.effective_chat
            and update.effective_chat.type == "private"
            and update.effective_user
            and update.effective_user.id in self.allowed
        )

    def date(self, value: float) -> str:
        return datetime.fromtimestamp(value, self.timezone).strftime("%d %b %H:%M %Z")

    def render(self, trip: Trip, now: float) -> str:
        lines = [
            f"📍 {trip.label}",
            f"Arrival deadline: {self.date(trip.deadline)}",
        ]
        if trip.origin_lat is None:
            lines.append("Waiting for your location. Share live location in this chat.")
        else:
            lines.append(f"Location updated: {self.date(trip.location_at)}")
            if trip.stale(now):
                lines.append("⚠️ Location stale or sharing ended. Share a fresh location now.")
            if trip.warning:
                lines.append(f"⚠️ {trip.warning}")
            if trip.leave_at is not None:
                budget = math.floor((trip.leave_at - now) / 60)
                lines.extend(
                    [
                        f"Last route: {trip.route_label}",
                        f"Journey: {math.ceil((trip.arrive_at - trip.leave_at) / 60)} min",
                        f"Scheduled arrival: {self.date(trip.arrive_at)}",
                        f"Leave by: {self.date(trip.leave_at)}",
                        f"Route checked: {self.date(trip.route_at)}",
                    ]
                )
                if trip.stale(now) or trip.warning:
                    lines.append("Last successful estimate only — do not rely on this as current.")
                lines.append(
                    "🔴 LEAVE NOW — the estimated departure time has been reached."
                    if trip.leave_at <= now
                    else f"Wandering budget (estimate): {budget} min"
                )
            elif not trip.warning:
                lines.append("Waiting for a route estimate.")
        return "\n".join(lines)

    async def publish(self, api, trip: Trip, text: str) -> None:
        if text == trip.status_text and trip.status_id is not None:
            return
        if trip.status_id is not None:
            try:
                await api.edit_message_text(
                    chat_id=trip.chat_id,
                    message_id=trip.status_id,
                    text=text,
                    reply_markup=links(trip),
                )
            except BadRequest as error:
                if "message is not modified" in str(error).lower():
                    pass
                elif "message to edit not found" in str(error).lower():
                    trip.status_id = None
                else:
                    raise
        if trip.status_id is None:
            message = await api.send_message(trip.chat_id, text, reply_markup=links(trip))
            trip.status_id = message.message_id
        trip.status_text = text
        self.store.save(trip)

    async def refresh(self, api, trip: Trip, now: float) -> None:
        if trip.phase != "tracking":
            return
        if now >= trip.deadline:
            try:
                await self.publish(
                    api, trip, "Arrival deadline reached. Tracking ended; saved location deleted."
                )
            finally:
                self.store.delete(trip.chat_id)
            return
        if route_due(trip, now):
            trip.attempted_at = now
            try:
                route = await self.routes.calculate(trip)
                trip.leave_at, trip.arrive_at = route.leave_at, route.arrive_at
                trip.route_label, trip.route_at = route.label, now
                trip.route_lat, trip.route_lon = trip.origin_lat, trip.origin_lon
                trip.warning = ""
            except RouteUnavailable as error:
                trip.warning = str(error)
            self.store.save(trip)

        warning = (
            "Location stale or sharing ended. Share a fresh location; check your route manually."
            if trip.origin_lat is not None and trip.stale(now)
            else trip.warning
        )
        if warning and warning != trip.notified_warning:
            await api.send_message(trip.chat_id, f"⚠️ {warning}", reply_markup=links(trip))
        trip.notified_warning = warning
        self.store.save(trip)

        if trip.leave_at is not None:
            slack = trip.leave_at - now
            level = 2 if slack <= 0 else 1 if slack <= 900 else 0
            if level > trip.alert_level:
                alert = "🔴 LEAVE NOW" if level == 2 else "🟡 15 minutes or less left"
                await api.send_message(
                    trip.chat_id,
                    f"{alert}\nBased on route checked {self.date(trip.route_at)}.\n"
                    + self.render(trip, now),
                    reply_markup=links(trip),
                )
                trip.alert_level = level
                self.store.save(trip)
        await self.publish(api, trip, self.render(trip, now))

    async def command(self, update: Update, context) -> None:
        if not self.authorized(update):
            return
        message = update.effective_message
        # Ignore edited commands; only location edits change tracking state.
        if update.edited_message:
            return
        name = message.text.split()[0]
        name = name.split("@")[0]
        async with self.lock:
            if name in ("/start", "/help"):
                await message.reply_text(HELP)
                return
            chat_id = update.effective_chat.id
            if name == "/cancel":
                self.store.delete(chat_id)
                await message.reply_text("Tracking cancelled; saved trip and location deleted.")
                return
            if name == "/trip":
                self.store.save(Trip(chat_id, location_message_id=message.message_id))
                await message.reply_text("Send a destination pin.")
                return
            trip = self.store.get(chat_id)
            if trip is None or trip.phase == "destination":
                await message.reply_text("Send a destination pin to begin.")
                return
            if trip.phase == "time":
                await message.reply_text(
                    f"What time should you be there? HH:MM, in {self.timezone}."
                )
                return
            await self.refresh(context.bot, trip, time.time())

    async def arrival(self, update: Update, context) -> None:
        if not self.authorized(update) or update.edited_message:
            return
        message = update.effective_message
        async with self.lock:
            trip = self.store.get(update.effective_chat.id)
            if trip is None or trip.phase == "destination":
                await message.reply_text("Send a destination pin first.")
                return
            if trip.phase != "time":
                await message.reply_text("Already tracking. Use /trip to set a new pin and time.")
                return
            try:
                trip.deadline = parse_arrival(message.text, datetime.now(UTC), self.timezone)
            except ValueError as error:
                await message.reply_text(str(error))
                return
            trip.phase = "tracking"
            # Ignore edits to the destination pin and any earlier live-location messages.
            trip.location_message_id = message.message_id
            self.store.save(trip)
            await self.refresh(context.bot, trip, time.time())

    async def location(self, update: Update, context) -> None:
        if not self.authorized(update):
            return
        message = update.effective_message
        async with self.lock:
            trip = self.store.get(update.effective_chat.id)
            location = message.location or message.venue.location
            if trip is None:
                if update.edited_message:
                    return
                trip = Trip(update.effective_chat.id)
            # Old live-message edits must not supersede a newer sharing session.
            if message.message_id < trip.location_message_id:
                return
            if trip.phase != "tracking":
                if update.edited_message:
                    return
                if location.live_period:
                    await message.reply_text(
                        "Send the destination as a static pin first, not live location."
                    )
                    return
                trip.latitude, trip.longitude = location.latitude, location.longitude
                trip.label = message.venue.title[:120] if message.venue else "Your destination"
                trip.phase = "time"
                trip.location_message_id = message.message_id
                self.store.save(trip)
                await message.reply_text(
                    f"What time should you be there? HH:MM, in {self.timezone}."
                )
                return
            at = (message.edit_date or message.date).timestamp()
            if at < trip.location_at:
                return
            trip.origin_lat, trip.origin_lon = location.latitude, location.longitude
            trip.location_at, trip.location_message_id = at, message.message_id
            period = location.live_period
            if isinstance(period, timedelta):
                period = period.total_seconds()
            trip.live_until = message.date.timestamp() + period if period else at + 300
            # An edited location with no live_period indicates sharing was stopped.
            if update.edited_message and not period:
                trip.live_until = at
            self.store.save(trip)
            await self.refresh(context.bot, trip, time.time())

    async def tick(self, context) -> None:
        async with self.lock:
            for trip in self.store.all():
                if trip.chat_id not in self.allowed:
                    self.store.delete(trip.chat_id)
                    continue
                try:
                    await self.refresh(context.bot, trip, time.time())
                except Forbidden:
                    self.store.delete(trip.chat_id)
                except TelegramError:
                    LOG.warning("Telegram delivery failed; will retry on next timer tick")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    # HTTP client logs include Telegram tokens in URL paths.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    try:
        allowed = {int(v.strip()) for v in os.environ.get("ALLOWED_USER_IDS", "").split(",")}
        if not allowed or any(v <= 0 for v in allowed):
            raise ValueError
    except ValueError:
        raise SystemExit(
            "Set ALLOWED_USER_IDS to comma-separated positive Telegram user IDs."
        ) from None
    if not token or not key:
        raise SystemExit("TELEGRAM_BOT_TOKEN and GOOGLE_MAPS_API_KEY are required.")
    timezone = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Europe/London"))
    # Location database and directory are private to the service user.
    os.umask(0o077)
    store = Store(os.environ.get("DATABASE_PATH", "data/bot.sqlite3"))
    client = httpx.AsyncClient(timeout=20)
    bot = Bot(store, GoogleRoutes(key, client), allowed, timezone)

    async def shutdown(application):
        await client.aclose()
        store.close()

    async def error_handler(update, context):
        LOG.warning("Update failed (%s); sensitive details omitted", type(context.error).__name__)

    application = Application.builder().token(token).post_shutdown(shutdown).build()
    application.add_handler(
        CommandHandler(["start", "help", "trip", "status", "cancel"], bot.command)
    )
    application.add_handler(MessageHandler(filters.LOCATION | filters.VENUE, bot.location))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.arrival))
    application.add_error_handler(error_handler)
    application.job_queue.run_repeating(bot.tick, interval=30, first=1)
    application.run_polling(
        allowed_updates=["message", "edited_message"], drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
