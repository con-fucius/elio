# Elio — Domain Glossary

**Status:** Draft for Phase 0  
**Vertical flavor:** hospital (see ADR-007). Terms marked **(cross-domain)** apply to marketing and collections as well.  
**Non-authoritative sources mined:** R1–R9, contract §3–§15. Conflicts resolved toward the canonical baseline and these definitions.

---

## System boundary

| Term | Definition |
|---|---|
| **Elio** | The field-work execution and control platform. Not an EMR, CRM, loan system, payment processor, or surveillance product. |
| **Work-execution layer** | Elio orchestrates assignment, authorized execution, evidence, outcome, and review. It does not replace systems of record (patient record, CRM, core banking, payment settlement). |
| **Projection** | Any worker- or supervisor-facing view (the "work card", queue, detail screen). A projection never defines domain state; it renders it. |

---

## Actors and tenancy

| Term | Definition |
|---|---|
| **Tenant** | Top-level isolation boundary (customer organisation). All operational data is tenant-scoped. |
| **Organisation** | Operating unit within a tenant (facility, territory, branch). Optional mid-level for assignment scoping. |
| **Actor** | Any authenticated principal: human user or service account. |
| **Field worker** | Actor who executes assigned work in the field. Primary PWA user. |
| **Supervisor** | Actor who assigns, reviews, reassigns, escalates, and overrides within authority. |
| **Operations manager** | Actor with cross-team operational visibility; no implicit override of policy. |
| **Compliance/audit user** | Actor with read access to audit and sensitive reporting; no operational mutation rights by default. |
| **Platform administrator** | Technical operator of Elio. Must not have silent god-mode over business state; privileged actions are audited. |
| **Service account** | Non-human actor for integrations. Credentials and privileges separate from humans. |
| **DeviceSession** | Registered client installation/session bound to an actor. Supports revocation on loss or compromise. Not the same as an authentication token alone. |

---

## Core work model **(cross-domain)**

| Term | Definition |
|---|---|
| **WorkItem** | The unit of operational work. Has identity, type, state, validity window, authority/policy reference, and outcome schema. Exists before and independently of any single assignment. |
| **WorkTemplate** | Optional reusable definition of a class of work items (checklist shape, evidence requirements, outcome schema). Instantiation creates WorkItems. |
| **Assignment** | Grant of responsibility for executing a WorkItem to an Actor or team, for a window, with an authority snapshot/reference. Mutable through controlled transitions (reassign, revoke, cancel), never silent overwrite. |
| **Task** | A required step inside a WorkItem's execution plan. Ordered or checklist-shaped. Not a separate lifecycle aggregate in Phase 0 — state rolls into the WorkItem. |
| **Context** | The minimum information exposed to an actor to execute a WorkItem (facility record ref, equipment ref, case ref, outlet ref). Context is referenced, not copied into a parallel master record. |
| **Action** | A material step performed during execution (start, observe, record structured result, raise exception, attach evidence). Action is an event-class object with actor, timestamps, and policy version. |
| **Outcome** | The typed result of execution (e.g. COMPLETED / PARTIALLY_COMPLETED / FAILED / UNABLE_TO_ACCESS / REFERRED / REQUIRES_FOLLOW_UP). Not free-text alone. |
| **Exception** | First-class record that normal execution could not proceed (blocked, unsafe, wrong assignment, insufficient authority, missing information, customer unavailable, technical failure). Distinct from a failed outcome that still completed the workflow. |
| **Review** | Controlled management intervention on a WorkItem or its submission (accept, reject, correct, reassign, escalate) with reason and audit. |
| **Next Action** | A follow-on WorkItem or Assignment created from an outcome or review. Not an informal note. |

---

## Authority and policy

| Term | Definition |
|---|---|
| **Authority / Policy** | What an actor may do, under which conditions, with which limits. Evaluated as `actor + tenant + role + assignment + work state + action + context + policy version → ALLOW \| DENY \| REQUIRE_REVIEW`. |
| **Policy** | Versioned, immutable-once-effective rule set for a domain/action class. |
| **PolicyVersion** | Immutable effective version. Historical decisions pin the version they used. |
| **Override** | Controlled decision change with override actor, reason code, free-text where required, original decision, new decision, policy version, timestamp. Elevated authorization for sensitive overrides. |
| **Offline safety class** | Classification of an action for offline execution: **Class A** safe offline (observe, draft, capture evidence, raise exception); **Class B** conditionally offline (complete work within a validity envelope); **Class C** online-required (financial obligation change, high-consequence health action, newly restricted sensitive data access, authority revocation). |

---

## Execution, evidence, time

| Term | Definition |
|---|---|
| **Execution** | The period and record of performing an Assignment, including Actions, partial progress, and Exceptions. |
| **Evidence** | First-class object supporting claims about an Action or Outcome. Never automatically equal to truth. Types include structured observation, photo, document, worker declaration, server system observation, customer/facility acknowledgement. |
| **Evidence status** | CAPTURED → UPLOADED → VERIFIED \| REJECTED \| DISPUTED \| EXPIRED. |
| **Provenance** | Who captured, on which device/session, client time, server receipt time, source type, integrity metadata (checksum), verification status, retention class. |
| **Location evidence** | Event-scoped latitude/longitude/accuracy/source/purpose captured at a relevant action. Not continuous tracking. Not proof of presence by itself. |
| **client_time** | Device-reported time. Useful as provenance. **Not authoritative** for legal/business chronology. |
| **server_received_time** | Server clock when a command/evidence was accepted into processing. |
| **server_event_time** | Server-authoritative ordering/chronology for business events. |
| **Idempotency key** | Client-generated key; unique per `(tenant_id, actor_id, idempotency_key)`. Retry with same key + same payload returns original result; same key + different payload is rejected. |
| **Command** | Client request to change authoritative state. Never a direct write. |
| **Event** | Server-accepted record that a state transition occurred. |
| **AuditEntry** | Append-oriented business audit record (actor, tenant, action, aggregate, before/after, policy, reason, correlation, source). Separate from application logs. Survives ordinary app errors. Not modifiable by normal users. |
| **Outbox** | Durable row written in the same DB transaction as business state + audit, for asynchronous workers (integrations, notifications). Prevents "committed but event lost." |

---

## Sync **(cross-domain)**

| Term | Definition |
|---|---|
| **PendingCommand** | Locally persisted command not yet accepted by the server. Survives restart. |
| **SyncCursor** | Opaque server change cursor. Advanced only after durable local persistence of the download batch. |
| **Conflict** | Server-side determination that a command cannot be applied cleanly under domain semantics. Categories are explicit; unknown → REVIEW_REQUIRED. |
| **RequiresReview** | Server response class: accepted into the system but held for human review; not the same as rejected. |
| **Reconciliation** | Process of bringing local projection and server authority into a known consistent state after conflict, partial sync, or correction. |

---

## Hospital vertical specifics **(Phase 0 modeling vehicle)**

| Term | Definition |
|---|---|
| **Facility** | Health facility or designated site where work occurs. Referenced by Context; not owned as a parallel master if an authoritative facility registry exists externally. |
| **Equipment / asset** | biomedical or facility equipment under service/inspection work. Authoritative asset record may live in an external system. |
| **Field checklist** | Ordered Task set for a hospital WorkItem type (inspection, service intervention, supply/commodity operational task, non-clinical outreach ops task). |
| **Non-clinical work** | Work that does not create or update a patient clinical record. Default Phase-1 hospital scope. |
| **Patient-identifiable health information** | Any data that identifies or can be linked to a patient. Out of Phase-1 core unless an explicit later gate (DPIA, security review, integration design) is cleared. |
| **EMR/HMIS boundary** | Elio must not become the authoritative patient record or clinical decision system. Hospital WorkItems reference operational context only. |

---

## Explicit non-entities (do not model as core aggregates in Phase 1)

- Customer master / patient master (reference external systems)
- Payment settlement / ledger (acknowledgement only)
- Route plan (not a primary object)
- Chat / messaging thread
- AI recommendation object
- Generic workflow DSL node

---

## Open glossary items (deliberately unresolved)

1. Exact outcome enum values per hospital WorkItem type — pending checklist authoring with the health partner when available.
2. Whether Team is a first-class assignment target or Actor-only — keep Actor-only until multi-party work is proven necessary.
3. Retention class taxonomy values — deferred to data-inventory work, not Phase 0 model freeze.
