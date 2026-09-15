# ADR-003: PWA field client for Phase 1; native Android deferred

**Status:** Accepted  
**Date:** 2026-05 (working session)  

## Context

Field execution is the product. Early planning swung between native Android (Kotlin + Compose) and PWA. Native offers superior offline, background, and device control; PWA avoids a second client codebase and fits "do not blow out of proportion."

## Decision

Phase 1 field client is a **PWA**: React + TypeScript + Vite, service worker for app shell, IndexedDB for durable local state, explicit sync engine. Native Android is out of Phase 1.

The PWA must meet native-grade engineering principles: local-first interaction, durable offline queue, idempotent commands, optimistic UI with authoritative reconciliation, explicit pending/conflict surfacing (not resume-only). Background sync is **not** assumed guaranteed; the protocol must remain correct when it does not run.

## Consequences

- Single client path to harden.
- Real-device testing on low-end Android + poor networks is mandatory before pilot.
- Escape hatch to native exists only if field evidence shows a hard browser limitation (guaranteed background execution, deep OS integration, peripherals, heavy offline workloads). Backend and sync protocol must not assume PWA-only forever.
