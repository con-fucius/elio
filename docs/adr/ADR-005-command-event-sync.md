# ADR-005: Command/event sync, not CRUD replication

**Status:** Accepted  
**Date:** 2026-05 (working session)  

## Context

Offline clients naturally tempt teams toward "sync two databases" or generic CRUD merge. Both create distributed-database problems and silent data loss under conflict.

## Decision

- The client never mutates authoritative business state directly.
- The client emits **commands** (e.g. AcceptAssignment, StartWork, SaveWorkDraft, SubmitWork, RaiseException, AttachEvidence) with `command_id`, `idempotency_key`, `schema_version`, `client_sequence`, `client_created_at`, `payload`.
- The server authenticates, authorizes, validates schema/state/policy/invariants, executes a DB transaction, writes business state + event + audit + outbox, returns an authoritative result.
- The client advances its sync cursor only after **durable local persistence** of that result.
- Conflicts are domain-classified. Unknown conflict → REVIEW_REQUIRED. Never silent last-write-wins for material state. Never silently discard a material event.

## Consequences

- Sync is a first-class subsystem on both client and server, not an HTTP helper.
- Every material mutation requires an idempotency key with unique `(tenant_id, actor_id, idempotency_key)`.
- Full event sourcing is not adopted; we need event-like auditability and command semantics, not an event-sourced database.
- **Batch upload is not all-or-nothing.** The server returns a **per-command result list** keyed by `command_id` (`accepted | rejected | requires_review | conflict | retryable` with reason). A mixed batch partially applies. This is required by stress-test S-10 and is binding when the sync API is designed.
