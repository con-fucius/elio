# ADR-004: Modular monolith backend, Postgres source of truth

**Status:** Accepted  
**Date:** 2026-05 (working session)  

## Context

The system is transactional, stateful, and multi-tenant. Biggest early risk is consistency complexity, not scale. Microservices, Kafka, and Kubernetes were considered and rejected for Phase 1.

## Decision

- **FastAPI modular monolith** with explicit internal modules (identity, tenancy, work, assignment, authority, execution, evidence, outcome, exception/review, sync, audit, notifications, integrations, reporting).
- **PostgreSQL** is the sole source of truth for operational/business state.
- **S3-compatible object storage** for evidence/media.
- **Transactional outbox** (DB transaction writes business state + audit + outbox event atomically) with background workers. No message broker in Phase 1.
- Structural decoupling via module boundaries and contracts, not network calls.

## Consequences

- No premature distributed-system failure modes.
- Module boundaries must be enforced in code review; a module may not reach into another module's tables except through explicit interfaces.
- A broker may be introduced later only behind the outbox boundary, when load or integration complexity justifies it.
