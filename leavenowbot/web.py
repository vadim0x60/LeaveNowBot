import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import tasks_v2
from google.oauth2 import id_token
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from telegram import Update
from telegram.ext import Application

from leavenowbot.app import Bot, add_handlers
from leavenowbot.routes import GoogleRoutes
from leavenowbot.store import Store
from leavenowbot.tasks import Scheduler

LOG = logging.getLogger(__name__)
UPDATE_ERROR: ContextVar[Exception | None] = ContextVar("update_error", default=None)


@dataclass(frozen=True)
class Config:
    token: str
    maps_key: str
    webhook_secret: str
    allowed: set[int]
    timezone: ZoneInfo
    project: str
    task_location: str
    task_queue: str
    task_service_account: str

    @classmethod
    def from_env(cls) -> "Config":
        values = {
            name: os.environ.get(name, "").strip()
            for name in (
                "TELEGRAM_BOT_TOKEN",
                "GOOGLE_MAPS_API_KEY",
                "TELEGRAM_WEBHOOK_SECRET",
                "GOOGLE_CLOUD_PROJECT",
                "TASK_LOCATION",
                "TASK_QUEUE",
                "TASK_SERVICE_ACCOUNT",
            )
        }
        try:
            allowed = {int(value.strip()) for value in os.environ["ALLOWED_USER_IDS"].split(",")}
            if not allowed or any(value <= 0 for value in allowed):
                raise ValueError
        except (KeyError, ValueError):
            raise RuntimeError(
                "Set ALLOWED_USER_IDS to comma-separated positive Telegram user IDs."
            ) from None
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            token=values["TELEGRAM_BOT_TOKEN"],
            maps_key=values["GOOGLE_MAPS_API_KEY"],
            webhook_secret=values["TELEGRAM_WEBHOOK_SECRET"],
            allowed=allowed,
            timezone=ZoneInfo(os.environ.get("BOT_TIMEZONE", "Europe/London")),
            project=values["GOOGLE_CLOUD_PROJECT"],
            task_location=values["TASK_LOCATION"],
            task_queue=values["TASK_QUEUE"],
            task_service_account=values["TASK_SERVICE_ACCOUNT"],
        )


async def verify_cloud_task(request: Request, service_account: str) -> bool:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return False
    token = authorization.removeprefix("Bearer ")
    try:
        claims = await run_in_threadpool(
            id_token.verify_oauth2_token,
            token,
            GoogleAuthRequest(),
            str(request.url),
        )
    except ValueError:
        return False
    return bool(
        claims.get("email_verified")
        and claims.get("email") == service_account
        and claims.get("iss") in {"accounts.google.com", "https://accounts.google.com"}
    )


def create_app(
    config: Config | None = None,
    *,
    store=None,
    routes=None,
    tasks_client=None,
    task_verifier: Callable[[Request, str], Awaitable[bool]] = verify_cloud_task,
) -> Starlette:
    config = config or Config.from_env()
    http = httpx.AsyncClient(timeout=20)
    store = store or Store(config.project)
    routes = routes or GoogleRoutes(config.maps_key, http)
    tasks_client = tasks_client or tasks_v2.CloudTasksAsyncClient()
    scheduler = Scheduler(
        store,
        tasks_client,
        config.project,
        config.task_location,
        config.task_queue,
        config.task_service_account,
    )
    bot = Bot(store, routes, config.allowed, config.timezone)
    telegram = Application.builder().token(config.token).build()
    add_handlers(telegram, bot)

    async def error_handler(update, context):
        LOG.warning("Update failed (%s); sensitive details omitted", type(context.error).__name__)
        UPDATE_ERROR.set(context.error)

    telegram.add_error_handler(error_handler)

    @asynccontextmanager
    async def lifespan(app):
        await telegram.initialize()
        await telegram.start()
        try:
            yield
        finally:
            await telegram.stop()
            await telegram.shutdown()
            await http.aclose()
            if isinstance(store, Store):
                store.client.close()
            close_tasks = getattr(getattr(tasks_client, "transport", None), "close", None)
            if close_tasks:
                await close_tasks()

    async def health(request: Request) -> Response:
        return PlainTextResponse("ok")

    async def webhook(request: Request) -> Response:
        supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not hmac.compare_digest(supplied.encode(), config.webhook_secret.encode()):
            return PlainTextResponse("forbidden", status_code=403)
        try:
            update = Update.de_json(await request.json(), telegram.bot)
        except (TypeError, ValueError):
            return PlainTextResponse("invalid update", status_code=400)
        error_token = UPDATE_ERROR.set(None)
        try:
            await telegram.process_update(update)
            if error := UPDATE_ERROR.get():
                raise error
        finally:
            UPDATE_ERROR.reset(error_token)
        if bot.authorized(update):
            trip = await store.get(update.effective_chat.id)
            if trip is not None:
                await scheduler.schedule(trip, str(request.url_for("task_check")))
        return Response(status_code=204)

    async def task_check(request: Request) -> Response:
        if not await task_verifier(request, config.task_service_account):
            return PlainTextResponse("forbidden", status_code=403)
        try:
            body = await request.json()
            chat_id, token = int(body["chat_id"]), str(body["token"])
        except (KeyError, TypeError, ValueError):
            return PlainTextResponse("invalid task", status_code=400)
        trip = await store.get(chat_id)
        if trip is None or not hmac.compare_digest(trip.task_token, token):
            return Response(status_code=204)
        await bot.tick(telegram.bot, chat_id)
        trip = await store.get(chat_id)
        if trip is not None:
            await scheduler.schedule(trip, str(request.url))
        return Response(status_code=204)

    app = Starlette(
        routes=[
            Route("/healthz", health, methods=["GET"]),
            Route("/telegram", webhook, methods=["POST"]),
            Route("/tasks/check", task_check, methods=["POST"], name="task_check"),
        ],
        lifespan=lifespan,
    )
    app.state.bot = bot
    app.state.telegram = telegram
    app.state.scheduler = scheduler
    return app


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    # HTTP client logs include Telegram tokens in URL paths.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
