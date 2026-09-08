# ADR 0002: Scale to zero on Google Cloud

Status: Accepted

## Context

Expected use is approximately one hour-long tracking session per month. ADR 0001 chose a continuously running long-polling process and local SQLite to minimize deployment components. Keeping that process allocated during weeks of inactivity is a poor match for the actual workload.

Telegram webhooks can wake request-driven compute, but the bot also needs checks when no location update arrives. These checks detect stale sharing, refresh stationary routes, update status, and deliver departure alerts. Any replacement for the process timer must survive instance shutdown. Persisted trip state must likewise live outside an ephemeral instance.

## Decision

Run an ASGI webhook service on Cloud Run with zero minimum instances. Store each chat’s active trip as one Firestore document. During active tracking, chain one-shot Cloud Tasks: each task invokes the service, performs one check, and schedules the next required check. A fresh location retains the existing 30-second cadence; after location becomes stale, schedule only alert and deadline boundaries until a webhook supplies new coordinates.

Authenticate Telegram calls with its webhook secret header. Authenticate task calls with a Google-signed OIDC token from a dedicated service account, then compare a random task token with the current token in Firestore. New updates supersede older scheduled tasks without requiring deletion from the queue.

Limit Cloud Run to one instance and one concurrent request. This preserves the existing serialized read/change/write and Telegram delivery flow without distributed locking. Use separate runtime, task-caller, and build service accounts. Keep Telegram, Routes, and webhook secrets in Secret Manager. Provision infrastructure declaratively with Terraform and build the container with Cloud Build.

## Consequences

The service scales to zero between webhooks and scheduled work. Firestore, Cloud Tasks, Secret Manager, Artifact Registry, and Cloud Run replace the persistent host and filesystem. At the expected usage, all are consumption-based and operational overhead is low, though the project now depends more deeply on Google Cloud.

Cloud Run must accept unauthenticated network ingress because Telegram cannot present Google IAM credentials. Application-level webhook authentication remains mandatory. The task endpoint independently verifies OIDC identity. Firestore location is a permanent deployment choice.

The single-instance limit intentionally favors correctness and simplicity over throughput; it suits a private allowlisted bot, not a public service. At-least-once delivery remains. Task tokens and persisted alert levels suppress normal duplicates, but Telegram delivery and Firestore cannot commit atomically, so a crash in between can duplicate a notification.

Cloud Storage objects were considered for persistence. They would also scale to zero, but Firestore provides a more direct document read/change/write API and leaves room for transactional compare-and-set if concurrency requirements change. Memorystore and Cloud SQL retain provisioned capacity that is unjustified for this workload.
