# ADR-006: Server-authoritative policy/authority module, not a generic rules engine

**Status:** Accepted  
**Date:** 2026-05 (working session)  

## Context

Authorization here is not role-check-in-route-handler. It depends on actor, tenant, role, assignment, work state, action, context, and policy version. A generic visual rules engine or decision marketplace is out of scope and dangerous.

## Decision

- Implement a **versioned, deterministic policy module** in the backend.
- Decision shape: `ALLOW | DENY | REQUIRE_REVIEW`.
- Policies are immutable once effective; changes create new versions. Historical decisions are not silently invalidated.
- Every authoritative decision records `policy_id`, `policy_version`, `decision`, `reason_code`.
- No business-critical authorization logic may live only in the React client. The client reflects permissions; the server enforces them.
- Human override is a controlled, audited state transition — not an admin bypass.

## Consequences

- Policy evaluation must be unit- and property-testable.
- Offline clients cache a policy version with an explicit validity/staleness envelope; high-risk actions require fresh policy (see pending-sync design and stress-test matrix).
- No rules DSL or designer in Phase 1 — configuration and code with reason codes.
