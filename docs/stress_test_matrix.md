# Phase 0 Stress-Test Matrix — Model vs Failure/Abuse

**Status:** Phase 0 gate artifact  
**Inputs:** contract invariants INV-001–015; R4 threat/abuse; R5 failure/drift; hospital state machine; pending-sync design; glossary  
**Purpose:** Find holes in the **model** before API surface or monorepo. Not a test plan for code that does not exist yet — each row is a design requirement or a known gap.

Legend for **Disposition**:

- **HOLD** — model handles it; keep as binding requirement
- **GAP** — hole or underspecification; must resolve before Phase 1 freeze
- **DEFER** — real but intentionally later (with trigger)

---

## 1. Sync / offline

| ID | Scenario | Model answer | Disposition |
|---|---|---|---|
| S-01 | Worker submits; response lost; retries | Idempotency key returns original result | HOLD |
| S-02 | Worker submits; server commits; browser killed before local ACCEPTED persist | Cursor/command status must not advance before durable persist; on relaunch same key retries → ACCEPTED | HOLD (pending-sync §5.2; INV-006/007) |
| S-03 | Worker closes app believing done; never reopens for 3 days | Global chrome + end-of-day interstitial + ops backlog metrics; cannot force reopen | HOLD (pending-sync) — residual risk: work stuck on dead device |
| S-04 | Two browser tabs, same actor, same command key, different payloads | Same key + different payload → reject | HOLD |
| S-05 | Two devices, same actor, different commands on same WorkItem | Server serializes via WorkItem.version / state machine; loser gets conflict or illegal transition | HOLD — need explicit concurrency rule: **one active assignment**, second device only if policy allows multi-device (default: no) |
| S-06 | SubmitWork arrives after server CANCELLED | Illegal transition / conflict; never COMPLETED | HOLD |
| S-07 | SubmitWork arrives after REASSIGN to other worker | Assignment check fails → REJECTED/conflict | HOLD |
| S-08 | Policy changed while worker offline; worker submits Class B | Server evaluates **current** policy; may DENY or REQUIRE_REVIEW; client must not assume cached policy is final | HOLD |
| S-09 | Policy changed; Class C attempted offline | Client blocks Class C offline | HOLD |
| S-10 | Partial batch: 10 commands, server accepts 7, rejects 3 | Per-command results; cursor for downloads separate from upload acks | HOLD — **GAP note:** upload response schema must be per-command, not whole-batch all-or-nothing |
| S-11 | Clock skew: client_time in the future | client_time provenance only; server_event_time authoritative | HOLD (INV-008) |
| S-12 | Evidence upload succeeds, metadata command still queued | Evidence status UPLOADED vs VERIFIED separate from WorkItem outcome | HOLD |
| S-13 | Quota full mid-shift | Explicit storage error; no silent drop | HOLD (PS-7) |
| S-14 | Server unavailable 24h | Class A/B continue under envelopes; backlog visible | HOLD |

**S-10 GAP resolution required:** sync upload API returns a **result list** keyed by command_id (accepted | rejected | requires_review | conflict | retryable), not a single batch status. Freeze this in ADR-005 addendum when API design starts.

---

## 2. Authority / abuse

| ID | Scenario | Model answer | Disposition |
|---|---|---|---|
| A-01 | Fake completion (no real work) | Typed outcome + evidence requirements + risk-based review; hospital review required by default | HOLD — does not eliminate fraud; detects some |
| A-02 | GPS spoof | Location = evidence with accuracy/source; never sole proof | HOLD |
| A-03 | Evidence from another visit | Bind evidence to work_item_id + action; provenance; optional capture challenge | HOLD |
| A-04 | Offline policy bypass after revoke | Server re-auth on sync; stale Class B → conflict | HOLD |
| A-05 | Duplicate payment/order style double-submit | Idempotency + unique business keys where applicable | HOLD (collections/marketing more than hospital Phase 0) |
| A-06 | Supervisor collusion / bulk rubber-stamp | Override + review audit; override_rate metric; separate duties for high-risk | HOLD — Phase 1 may need sampling rules |
| A-07 | Tenant crossover | Tenant scope at service + DB + tests (INV-001) | HOLD |
| A-08 | Malicious integration forged work | Signed service accounts, schema validation, attribution | DEFER until first real integration |
| A-09 | Worker mutates IndexedDB to fake local state | Server is authority; local tamper cannot create server COMPLETED without passing server validation | HOLD — cannot fully prevent local lie; server must not trust client state claims |
| A-10 | Collections harassment patterns | Out of Phase 0 hospital model; collections profile later | DEFER — collections vertical gate |

---

## 3. State machine holes (found by this stress-test)

| ID | Finding | Resolution |
|---|---|---|
| SM-01 | Contract used ACCEPTED for two meanings | Fixed: worker-accept only; review success → COMPLETED |
| SM-02 | FAILED as state ambiguous with outcomes | Fixed: Outcome enum on submit; BLOCKED is the stuck state |
| SM-03 | REJECTED auto-return to IN_PROGRESS unsafe if assignment expired | Fixed: explicit ResumeWork / Resubmit / Reassign / Cancel |
| SM-04 | No path for worker to withdraw a SUBMITTED command still in flight | **GAP:** add conceptual command `WithdrawSubmission` allowed only while SUBMITTED and before UNDER_REVIEW begins; server rejects if review already started |
| SM-05 | CANCELLED while worker IN_PROGRESS offline | Covered by S-06; client should surface cancel on next download before submit when possible | HOLD |
| SM-06 | Double ACCEPTED from two devices | Default single active assignment; AcceptAssignment idempotent per assignment | HOLD |
| SM-07 | Expire vs Cancel ambiguity | EXPIRED = system time window; CANCELLED = human/system decision with reason | HOLD |

**SM-04 GAP:** Add `WithdrawSubmission` to state machine doc as SUBMITTED → (back to IN_PROGRESS or CANCELLED per rules). Do before Phase 1 freeze.

---

## 4. Hospital / privacy

| ID | Scenario | Model answer | Disposition |
|---|---|---|---|
| H-01 | Worker pastes patient identifier into notes | Phase 1: no patient-identifiable data in schema; free-text still a residual risk | **GAP** — need soft guidance + optional detection later; DPIA/live data gate before any real patient field |
| H-02 | Photo of patient inadvertently | Evidence type policy + training + review; not fully technical | HOLD with residual risk |
| H-03 | Lost device with offline health-adjacent ops data | DeviceSession revoke; local encryption expected; unsynced data unrecoverable | HOLD |
| H-04 | Audit contains sensitive payload | Audit stores references/reason codes; minimize payload dump | HOLD (INV-013) |
| H-05 | Elio drifts into EMR | Glossary non-entities; no patient master aggregate | HOLD — enforce in schema review |

**H-01 GAP:** before live regulated data: DPIA + data inventory + free-text policy. Does not block Phase 0 platform bring-up with synthetic/non-patient fixtures.

---

## 5. Reliability / ops

| ID | Scenario | Model answer | Disposition |
|---|---|---|---|
| R-01 | Worker works entire day offline | Class A/B envelopes; 8–12h target; pending chrome | HOLD |
| R-02 | Supervisor offline | Assign/review not Class A; backlog waits | HOLD |
| R-03 | Outbox worker crash after commit | Outbox row remains; retry | HOLD |
| R-04 | Object storage down | Evidence upload RETRYABLE; core state not blocked forever on 12MB photo | HOLD |
| R-05 | Notification failure | Notifications advisory only; never corrupt work state | HOLD |
| R-06 | Stale client version after schema change | schema_version + minimum_supported_client_version; forced upgrade rules | HOLD — Phase 1 needs explicit minimum version policy |
| R-07 | Mass reassignment | Assignment transitions auditable; history not rewritten | HOLD |

---

## 6. Model philosophy checks

| ID | Principle from user/brainstorm | Stress-test result |
|---|---|---|
| P-01 | No silent failure | CONFLICT/REJECTED/REQUIRES_REVIEW explicit; no empty lists to hide errors | HOLD |
| P-02 | Evidence ≠ truth | Glossary + hospital guards | HOLD |
| P-03 | Human override auditable | Override model retained | HOLD |
| P-04 | Adaptive capacity | Offline classes + degraded surfaces | HOLD |
| P-05 | Anomalies as lessons | Drift metrics in pending-sync + observability | HOLD — ops process is later |
| P-06 | Do not over-fit generic workflow engine | Single hospital machine + profiles; no DSL | HOLD |
| P-07 | Over-specification of contract schemas | Canonical baseline §3 marks field lists provisional | HOLD |

---

## 7. Must-fix before Phase 1 freeze (GAP list)

1. **S-10:** Per-command upload results (add to ADR-005 when API starts).
2. **SM-04:** WithdrawSubmission transition in state machine doc.
3. **H-01:** Free-text / patient-identifier handling policy (can be written pre-DPIA as design constraint; enforced before live data).
4. **Single active assignment default** made explicit in assignment module design (S-05).

These are small, concrete. None requires monorepo or code.

---

## 8. What this stress-test does *not* prove

- That the PWA performs on actual Kenyan low-end devices (needs Phase 1 + real devices).
- That hospital partner workflows fit the checklist shapes (needs partner).
- That DPIA/ODPC obligations are met (needs legal process).
- Commercial viability (explicitly out of scope).

It proves only that the **core model** (machine + authority + evidence + pending sync + glossary) has a coherent answer to the failure and abuse classes we already know matter.

---

## 9. Phase 0 completion checklist (updated)

- [x] Authority stack / canonical baseline
- [x] ADRs 001–007
- [x] Glossary
- [x] Hospital state machine
- [x] Pending-command surfacing design
- [x] Stress-test matrix
- [x] Apply GAP fixes: WithdrawSubmission; S-10 note in ADR-005; single-active-assignment default
- [ ] Owner review / sign-off before monorepo skeleton

Once you sign off, Phase 0 is closed and monorepo skeleton is unblocked.
