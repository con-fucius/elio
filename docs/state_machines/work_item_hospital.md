# WorkItem State Machine — Hospital vertical (Phase 0 draft)

**Status:** Authoritative draft for Phase 0. Provisional field lists elsewhere; this state model is binding for implementation once Phase 0 closes.  
**Scope:** Hospital WorkItem lifecycle. Marketing/collections may extend or restrict via domain profile; they may not invent a second core machine.  
**Supersedes:** The illustrative WorkItem diagram in `implementation_contract.txt` §4 where it conflicts (see §6).

---

## 1. Design rules

1. Every transition has an explicit predecessor, an authorization rule, and an audit event.
2. Illegal transitions are rejected server-side with a deterministic error. Never corrected silently.
3. Concurrent transitions cannot silently overwrite one another (optimistic concurrency on WorkItem.version).
4. Terminal states are explicit. Nothing "falls off" the machine.
5. Offline execution uses the same machine; the client may only propose transitions the server will accept under current policy (see offline classes).
6. Evidence arriving after SUBMITTED does not auto-complete; it attaches under an accepted transition or a correction command.
7. Same status name is never reused for two different semantic meanings.

---

## 2. States

### Active

| State | Meaning |
|---|---|
| `DRAFT` | Created, not yet releasable for assignment (template instantiation incomplete, or creator still editing under authority). |
| `READY` | Valid, releasable for assignment. Not yet assigned. |
| `ASSIGNED` | Responsibility granted; worker has not accepted. |
| `ACCEPTED` | Worker accepted responsibility. Not yet started execution. |
| `IN_PROGRESS` | Worker is executing (tasks, observations, evidence capture). |
| `BLOCKED` | Execution cannot proceed; Exception is open. Waiting on reassignment, unblock, cancel, or escalation. |
| `SUBMITTED` | Worker has submitted for review (or auto-complete rule fired). Awaiting review decision. |
| `UNDER_REVIEW` | Reviewer has actively engaged (optional intermediate; may be modeled as SUBMITTED + review assignment). Kept explicit so "in someone's queue" ≠ "nobody looking." |
| `REJECTED` | Review rejected submission. Requires rework path — does not auto-return to IN_PROGRESS without an explicit worker or supervisor command. |

### Terminal

| State | Meaning |
|---|---|
| `COMPLETED` | Accepted and closed successfully. No further mutation except controlled correction/reopen if policy allows. |
| `CANCELLED` | Work will not be performed (superseded, duplicate, out of window, worker unavailable with no reassignment). |
| `EXPIRED` | Validity window closed without completion and without a successor decision. Operational dead-letter; not the same as CANCELLED. |

### Explicitly not used (Phase 0)

- `FAILED` as a state — failure is an **Outcome** on a transition into CANCELLED, SUBMITTED (with failed outcome), or a path to COMPLETED-with-exception. A separate FAILED state caused ambiguity in R1–R9 drafts (`partially_completed`, `failed`, `blocked` all competed as states).
- `CLOSED` as a synonym for COMPLETED — one terminal success state only; review-before-complete is modeled by routing through SUBMITTED/UNDER_REVIEW.

---

## 3. Transitions

```text
DRAFT
  → READY                         [create/release command; actor: creator or ops with create authority]
  → CANCELLED                     [cancel; reason required]

READY
  → ASSIGNED                      [assign; actor: supervisor/ops with assign authority]
  → CANCELLED                     [cancel; reason required]
  → EXPIRED                       [system: validity_until passed with no assignment, if policy says auto-expire]

ASSIGNED
  → ACCEPTED                      [AcceptAssignment; actor: assignee]
  → ASSIGNED                      [reassign; new assignee; old assignment closed with reason]  // stays ASSIGNED
  → CANCELLED                     [cancel/revoke assignment; reason required]
  → EXPIRED                       [system: validity_until passed without accept, per policy]
  → READY                         [unassign without cancel, if policy allows → actually prefer: explicit Unassign → READY]

ACCEPTED
  → IN_PROGRESS                   [StartWork; actor: assignee]
  → CANCELLED                     [cancel; reason required; assignee or supervisor per policy]
  → EXPIRED                       [system: validity window closed after accept but before start]

IN_PROGRESS
  → BLOCKED                       [RaiseException(blocking); actor: assignee]
  → SUBMITTED                     [SubmitWork; actor: assignee; outcome required; required evidence present or explicit incomplete-with-exception path]
  → CANCELLED                     [cancel; reason required]
  → EXPIRED                       [system: validity window closed while in progress, per policy]

BLOCKED
  → IN_PROGRESS                   [ResolveException / Unblock; actor: assignee or supervisor]
  → SUBMITTED                     [SubmitWork with outcome UNABLE_TO_ACCESS / FAILED-equivalent typed outcome; assignee]
  → ASSIGNED                      [reassign from blocked; supervisor]
  → CANCELLED                     [cancel; reason required]
  → EXPIRED                       [system, per policy]

SUBMITTED
  → UNDER_REVIEW                  [BeginReview; actor: reviewer with review authority]
  → COMPLETED                     [auto-complete only if policy explicitly allows review-free completion for this work type; otherwise illegal]
  → REJECTED                      [RejectSubmission without formal queue entry, if policy allows direct reject]
  → CANCELLED                     [rare; supervisor cancel of submitted work; reason required; audited]

UNDER_REVIEW
  → COMPLETED                     [AcceptReview; reviewer; review decision recorded]
  → REJECTED                      [RejectSubmission; reason required; rework instructions optional]
  → IN_PROGRESS                   [ReturnToWorker for rework without full reject semantics, if policy distinguishes; else use REJECTED path only]

REJECTED
  → IN_PROGRESS                   [worker resumes after rework, if assignment still valid]
  → SUBMITTED                     [resubmit after offline correction, same assignment]
  → ASSIGNED                      [reassign]
  → CANCELLED                     [give up; reason required]

COMPLETED / CANCELLED / EXPIRED
  → (no normal outgoing transitions)


Exception-only path (not a state):
  COMPLETED → REOPENED-equivalent is NOT in Phase 0.
  Corrections after COMPLETED use a separate Correction command that creates audit + optional new WorkItem (Next Action), never silent mutation of a terminal state.
```

### Transition table (authoritative)

| From | To | Command / trigger | Actor authority (minimum) | Notes |
|---|---|---|---|---|
| DRAFT | READY | ReleaseWork | create/update authority | |
| DRAFT | CANCELLED | CancelWork | create/update authority | reason required |
| READY | ASSIGNED | AssignWork | assign authority | assignment record created |
| READY | CANCELLED | CancelWork | assign authority | reason required |
| READY | EXPIRED | system | policy | if auto-expire enabled |
| ASSIGNED | ACCEPTED | AcceptAssignment | assignee | |
| ASSIGNED | ASSIGNED | ReassignWork | assign authority | closes prior assignment, opens new; stays ASSIGNED |
| ASSIGNED | CANCELLED | CancelWork | assign or revoke authority | reason required |
| ASSIGNED | EXPIRED | system | policy | |
| ACCEPTED | IN_PROGRESS | StartWork | assignee | |
| ACCEPTED | CANCELLED | CancelWork | assignee or supervisor | reason required |
| ACCEPTED | EXPIRED | system | policy | |
| IN_PROGRESS | BLOCKED | RaiseException | assignee | exception category required |
| IN_PROGRESS | SUBMITTED | SubmitWork | assignee | outcome required |
| IN_PROGRESS | CANCELLED | CancelWork | supervisor (assignee only if policy) | reason required |
| IN_PROGRESS | EXPIRED | system | policy | |
| BLOCKED | IN_PROGRESS | ResolveException | assignee or supervisor | |
| BLOCKED | SUBMITTED | SubmitWork | assignee | outcome = unable/failed type |
| BLOCKED | ASSIGNED | ReassignWork | assign authority | |
| BLOCKED | CANCELLED | CancelWork | supervisor | reason required |
| BLOCKED | EXPIRED | system | policy | |
| SUBMITTED | UNDER_REVIEW | BeginReview | review authority | |
| SUBMITTED | COMPLETED | CompleteWork | policy (review-free types only) | hospital default: NOT allowed |
| SUBMITTED | REJECTED | RejectSubmission | review authority | reason required |
| SUBMITTED | IN_PROGRESS | WithdrawSubmission | assignee | only while still SUBMITTED and review not yet begun; illegal once UNDER_REVIEW |
| UNDER_REVIEW | COMPLETED | AcceptReview | review authority | review record mandatory |
| UNDER_REVIEW | REJECTED | RejectSubmission | review authority | reason required |
| UNDER_REVIEW | IN_PROGRESS | ReturnToWorker | review authority | rework |
| REJECTED | IN_PROGRESS | ResumeWork | assignee | if assignment valid |
| REJECTED | SUBMITTED | SubmitWork | assignee | resubmit |
| REJECTED | ASSIGNED | ReassignWork | assign authority | |
| REJECTED | CANCELLED | CancelWork | supervisor | reason required |

---

## 4. Hospital-specific guards (Phase 0)

These are vertical constraints on top of the generic machine. They are **policy predicates**, not new states.

1. **No patient-identifiable health information** in Context, Evidence, or Outcome payloads in Phase 1 hospital profile. Violating payload → command rejected at validation, not stripped silently.
2. **Review is required by default** for hospital WorkItem types unless a WorkTemplate explicitly marks review-free (e.g. low-risk checklist). Review-free is an exception, not the platform default.
3. **Evidence that claims clinical truth is rejected by schema.** Evidence types are operational (photo of equipment, facility condition, checklist result, worker declaration). UI copy must not say "verified clinical fact."
4. **Location** only when WorkTemplate declares a purpose. GPS is location evidence, not presence proof.
5. **Class C actions** (e.g. any future action that would touch patient identity, or change authority) cannot run offline.

---

## 5. Offline interaction with the machine

**Assignment concurrency default:** a WorkItem has **at most one active Assignment** at a time. Multi-device or multi-worker concurrent execution is not supported in Phase 0/1 unless a later policy explicitly enables it. AcceptAssignment / SubmitWork from a stale or superseded assignment is rejected or conflicted — never merged.

| Offline class | Allowed proposed transitions while offline | On sync |
|---|---|---|
| A | RaiseException, evidence capture (pending), draft structured results (local only) | Server validates against **current** WorkItem state and policy version |
| B | StartWork, SubmitWork, ResolveException — only while cached policy/assignment valid and WorkItem not known revoked | If server state moved (cancelled, reassigned, expired) → conflict or requires_review; never silent success |
| C | None | Must be online |

Critical: a client may only propose `SubmitWork` if its local projection still believes the WorkItem is `IN_PROGRESS` or `BLOCKED` and assignment is active. Server remains the sole judge. Stale submit → explicit conflict, not COMPLETED.

---

## 6. What this fixes vs the contract sketch

| Issue in contract §4 | Fix here |
|---|---|
| `ACCEPTED` used both after ASSIGNED and after review | Single meaning: worker accepted assignment. Review success → COMPLETED. |
| `FAILED` / `partially_completed` / `blocked` competing as states in R1–R9 | BLOCKED is a state; failure/partial are **Outcomes** on SubmitWork |
| Missing clear terminals | COMPLETED, CANCELLED, EXPIRED explicit |
| REJECTED auto→ IN_PROGRESS | Explicit ResumeWork / Resubmit / Reassign / Cancel |
| No DRAFT/READY split | DRAFT → READY for releasability |
| Hospital review optional by silence | Review required by default for hospital profile |

---

## 7. Related commands (not exhaustive API design)

Command names used above are conceptual. They map to the contract's command model (idempotency key, schema version, etc.) without freezing HTTP shapes in this document.

**Pending Phase 0:** map each transition to a command payload skeleton after stress-test (T7) confirms no hole (e.g. can a worker SubmitWork after CANCELLED via race? Server must reject deterministically — covered by illegal transition tests).

---

## 8. Marketing profile delta (note only, not implemented in Phase 0 draft)

Marketing will likely allow more review-free completion paths and different Outcome enums. That is a WorkTemplate/policy difference, not a different state machine. Do not fork states for marketing.
