# Elio — Canonical Baseline

**Status:** Authoritative intent  
**Supersedes:** `implementation_contract.txt` where conflicts exist with this document; all of R1–R9 (`brainstorm_child.txt`) for baseline purposes  
**Retains:** R1–R9 as a non-authoritative reference source for domain nuance, failure taxonomy, and offline-authority classing until explicitly absorbed into ADRs or state machines  

---

## 1. Authority stack

When two documents conflict, this order wins:

1. `docs/canonical_baseline.md` (this file)
2. `docs/adr/*` (numbered ADRs)
3. `docs/state_machines/*`, `docs/glossary.md`, `docs/pending_sync_surfacing.md`, `docs/stress_test_matrix.md`
4. `implementation_contract.txt` (architecture reference, not Phase-0 authority)
5. `brainstorm_parent.md` / `brainstorm_child.txt` (historical reasoning, never authoritative)

R1–R9 content is not discarded. Where it contributes material the baseline needs (domain nuance, offline authority classes, failure taxonomy), it is absorbed into the authoritative set above and cited. Where it contradicts the baseline, it is superseded and must not be implemented from.

---

## 2. Resolved decisions

### 2.1 Verticals

Both **hospital field work** and **marketing field work** are priority verticals. Neither is ranked above the other commercially or as a "wedge." Each must receive exhaustive, rigorous implementation when built.

**Modeling vehicle for Phase 0 (glossary, state machines, stress-test):** hospital. This is a technical choice only — hospital forces explicit handling of health-data boundaries, purpose limitation, and authority constraints earliest. It does not imply hospital ships first commercially.

**Collections** remains in scope as a third vertical. It is deferred until its legal classification and authority controls are validated against a real deploying entity. Collections does not block hospital or marketing.

The earlier R2/R9 recommendation ("marketing first for lowest regulatory burden") and the earlier contract recommendation ("hospital first because it forces privacy early") are both **superseded**. Order of exhaustive implementation is not a current constraint. Modeling order uses hospital for constraint density only.

### 2.2 PWA vs native

Phase 1 field client is **PWA** (React + TypeScript + Vite + IndexedDB + service worker). Native Android is explicitly out of Phase 1 and remains an architectural escape hatch only if field evidence demonstrates a hard requirement that browsers cannot meet (guaranteed background execution, deep device integration, hardware peripherals, demanding offline workloads).

### 2.3 Locked technology (Phase 1)

- Backend: Python 3.13+, `uv`, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL, pytest, Hypothesis, Testcontainers
- Frontend: TypeScript, React, Vite, pnpm, IndexedDB, service worker/PWA
- Infrastructure: Docker/OCI, Terraform/OpenTofu, managed PostgreSQL, S3-compatible object storage, managed secrets, managed load balancer, GitHub Actions
- Security: OIDC, server-side authorization, OWASP ASVS baseline, explicit privacy/data-protection controls

### 2.4 Explicit non-goals (Phase 1)

Native Android/iOS, microservices, Kubernetes, Kafka, RabbitMQ, GraphQL, event sourcing as the full persistence model, generic workflow/rules engine, AI decision-making, facial recognition, biometrics, continuous location tracking, payment processing, CRM replacement, EMR/HMIS replacement, accounting, broad analytics platform, consumer-facing app, arbitrary third-party integrations, multi-country, multi-region active/active.

The system is a **work-execution and control layer**, not an ERP.

### 2.5 Legal / business timing

There is no design partner, no field validation, and no DPIA yet. Which vertical goes to market first, exact Kenyan workflow shapes, and controller/processor mapping are **deferred**. They do not block Phase 0 (glossary, state machines, ADRs, stress-testing) or the platform skeleton, provided no live regulated data is processed before those gates are cleared.

Commercial wedge is explicitly out of scope for now.

---

## 3. Over-specification control

`implementation_contract.txt` contains precise schemas (command envelope, idempotency table shape, full WorkItem field list, evidence field list). These are **provisional engineering targets**, not frozen contracts. They may be revised when:

- domain glossary and state machines expose a gap or contradiction;
- stress-testing against failure/abuse cases shows a schema cannot hold;
- ADR process supersedes a prior choice.

What **is** binding now:

- the architectural direction (PWA, modular monolith, Postgres source of truth, command/event sync, idempotency, no silent last-write-wins, server-authoritative state, audit separate from logs);
- the critical invariants INV-001 through INV-015 from the contract, as test requirements;
- the offline/sync philosophy (durable local queue, cursor advance only after persistence, domain-classified conflicts).

What is **not** binding until the corresponding Phase-0 artifact is written and stress-tested:

- exact field lists on WorkItem / Evidence / Command;
- the specific WorkItem state machine shape in the contract (see `docs/state_machines/` for the authoritative draft);
- conflict-category enumeration;
- API surface details beyond the `/api/v1/` versioning rule and command-oriented endpoint philosophy.

---

## 4. Core domain thesis (binding)

The worker-facing "work card" is a projection. The real object chain is:

**WorkItem → Assignment → Authority/Policy → Context → Execution → Evidence → Outcome → Review → Next Action**

Commands request state change. Events record what the server accepted as having happened. The client never directly mutates authoritative business state.

---

## 5. Pending-command surfacing (binding direction)

"Detect pending work on resume" is insufficient. The pending-sync design in `docs/pending_sync_surfacing.md` is authoritative for how the PWA must make queued, conflicted, rejected, and stale work continuously visible and actionable — not only after an app resume. This is a Phase-1 requirement, not a polish item.

---

## 6. Phase 0 exit (current gate)

Before monorepo skeleton and before any API surface:

- [x] Authority stack defined
- [x] Vertical-ordering contradiction resolved
- [x] PWA decision reaffirmed
- [ ] First ADRs written
- [ ] Domain glossary drafted
- [ ] Hospital-vertical state machines drafted
- [ ] Pending-command surfacing design written
- [ ] Model stress-tested against failure/abuse cases from R4/R5 and contract

Phase 0 does **not** require design partner, DPIA completion, or commercial validation. Those gate production and live regulated data, not architecture bring-up.
