# ADR 0001: Telegram bot with explicit arrival time

Status: Superseded by [ADR 0002](0002-google-cloud-scale-to-zero.md)

## Context

We want departure reminders while walking around, without building an iOS app. Telegram can deliver location messages and edits through the Bot API. The user explicitly chose a destination pin and arrival time as sufficient V0 input.

## Decision

Use Python, python-telegram-bot long polling, Google Routes in transit mode, and SQLite. Accept a destination pin, an arrival time, and then live location in a private allowlisted chat. Default local times to Europe/London and do not infer flight deadlines or add buffers.

Receive both `message` and `edited_message` updates. Run a timer as well as handling GPS updates: stationary users still need notifications. Throttle route requests, flag stale locations and provider failures, and persist the mutable status message ID and alert levels across restarts.

Use arrival-time transit itineraries to derive the departure time from the first boarding minus the access walk. Subtracting journey duration from the deadline alone would ignore timetable gaps. Choose the latest feasible departure among the returned alternatives.

## Consequences

One process and outbound HTTPS are sufficient; there is no webhook deployment, user-account session, native app, or separate queue. The database must be on persistent storage. This design suits a personal bot, not a large public service.

The phone must share location voluntarily, and the Bot API cannot retrieve GPS on demand. Real-device verification is still necessary. Schedules and delivery are not guaranteed. Because SQLite and Telegram cannot update atomically, a crash between message delivery and database commit can produce a duplicate notification.

Calendar parsing, flight policies, driving routes, and a TDLib userbot are outside V0.
