# Pending-Command Surfacing & Operational Controls

**Status:** Authoritative Phase-1 requirement  
**Supersedes:** "Detect pending work on resume" as sufficient (contract §7). Resume detection remains necessary but is not sufficient.  
**Client:** PWA field worker surface (and mirrored in operations console where noted)

---

## 1. Problem

If the only surfacing of unsynchronized work is "on app resume, check the queue," field workers will:

- believe work is fully saved when it is only local;
- abandon the app mid-shift and never return before battery/network death;
- have no way to distinguish "safe on device" from "accepted by server" from "conflict waiting on me";
- supervisors will not see backlog until it is already an operational incident.

Browser background sync is not guaranteed. Design assumes the worker **may never reopen the app after a session ends**. Controls must make pending state visible at every meaningful surface, not buried in a settings screen.

---

## 2. Local command lifecycle (client states)

Every PendingCommand has exactly one client-side status:

| Status | Meaning | Worker-facing meaning |
|---|---|---|
| `LOCAL_DRAFT` | Not yet a command; form/checklist in progress | "Still editing on this device" |
| `QUEUED` | Persisted as a command, not yet sent | "Saved on this device. Not yet sent." |
| `IN_FLIGHT` | Upload attempted, awaiting response | "Sending…" |
| `ACCEPTED` | Server returned authoritative accept | "Sent. Confirmed by server." |
| `REQUIRES_REVIEW` | Server accepted into review hold | "Sent. Waiting on supervisor." |
| `CONFLICT` | Server rejected as conflict with authoritative state | "Needs attention. Assignment or work changed." |
| `REJECTED` | Server rejected (validation, authority, illegal transition) | "Not accepted. Reason: …" |
| `RETRYABLE_FAILURE` | Network/5xx after server may or may not have committed; will retry with same idempotency key | "Couldn't confirm. Will retry." |

**Never** collapse CONFLICT, REJECTED, or REQUIRES_REVIEW into a generic "sync error." Never show a bare spinner as the only signal.

---

## 3. Continuous surfacing (required surfaces)

### 3.1 Global app chrome (always available)

Persistent, non-dismissable strip or badge on every primary screen:

- **Count** of non-terminal commands (`QUEUED`, `IN_FLIGHT`, `RETRYABLE_FAILURE`, `CONFLICT`, `REJECTED`, `REQUIRES_REVIEW`).
- **State summary**, e.g. `3 waiting to send · 1 needs attention`.
- **Last successful sync** timestamp (server-confirmed, not "last attempt").
- Tap → opens Sync Center (§4).

No screen may hide the global count. Offline mode is not a toast that disappears.

### 3.2 WorkItem projection (per item)

On any work detail / card:

- Per-item sync stamp derived from that item's commands + authoritative projection version:
  - `On server`
  - `On device only`
  - `Sent · in review`
  - `Conflict`
  - `Rejected`
- Item list and detail use the same vocabulary. No "saved" without qualification.

### 3.3 End-of-flow acknowledgement

After any material action (submit, exception, start):

1. Immediate local UI state change (optimistic).
2. Explicit phrase: **"Saved on this device"** if QUEUED; **"Confirmed"** only when ACCEPTED.
3. If the action is Class B/C or high-consequence, the UI must show the distinction before the worker navigates away — not a 500ms toast.

### 3.4 Shift / day boundary

When the worker hits "end of day" or closes the last open WorkItem:

- If non-terminal commands exist → blocking (or strongly warned) interstitial: list counts, link to Sync Center, option to "keep working" / "try send now."
- Do not use a modal that can be dismissed without reading when CONFLICT or REJECTED exist.

### 3.5 Operations console

Supervisors/ops see per-worker and per-tenant:

- pending command backlog (age buckets: <1h, 1–8h, >8h, >24h)
- conflict / rejection rates
- workers with zero successful sync in N hours
- stale policy clients (policy_version behind current)

These are first-class operational metrics (ties to observability metrics in baseline).

---

## 4. Sync Center (dedicated surface)

A single place the worker can always reach in ≤2 taps from anywhere:

1. **Header:** last confirmed sync; connectivity state (online / offline / weak — if detectable).
2. **Needs attention** (top, sorted by severity): CONFLICT, REJECTED, REQUIRES_REVIEW.
   - Each row: work item title/id, human reason code + short explanation, next action the worker can take (e.g. "Resume work", "Contact supervisor", "Discard draft if wrong item").
3. **Waiting to send:** QUEUED / IN_FLIGHT / RETRYABLE_FAILURE with age and manual "Try now."
4. **Recently confirmed:** short list of last ACCEPTED for confidence.
5. **What counts as sent:** link to plain-language explanation (device vs server).

Rules:

- CONFLICT/REJECTED require an explicit resolution path or explicit "I understand; supervisor will see this" acknowledgment — never auto-clear.
- Idempotent "Try now" reuses the same idempotency key. No new command on retry tap.
- Sync Center works offline for local status; network actions disabled with explanation.

---

## 5. Operational controls (beyond UI)

### 5.1 Service worker / background

- Attempt background sync when browser supports it (`sync` / `periodicsync` where available).
- On every app start, focus, online event, visibility change → run sync attempt.
- **Do not assume** any of the above fire. Worker-visible state must be correct if none fire for days.

### 5.2 Durable queue guarantees

- PendingCommand table in IndexedDB is transactional with the local WorkItem projection update. No path may advance local UI state without writing the command (for material actions).
- Queue survives hard kill, storage pressure (within quota), and browser restart.
- Quota exceeded → explicit local error state surfaced in Sync Center ("Device storage full; cannot save more work safely") — not a silent drop.

### 5.3 Escalation (platform-side)

- Server-side: metric `pending_commands` and `sync_failure_rate` per tenant/actor.
- Alert when: actor has CONFLICT/REJECTED open > threshold; actor zero ACCEPTED > shift length; tenant conflict rate > agreed threshold.
- These alert **operators**, not the worker's personal phone (no surprise SMS campaign in Phase 1 unless partner requires).

### 5.4 Lost / replaced device

- DeviceSession revocation clears ability to sync further commands from that session.
- Unsynced local work on a dead device is unrecoverable by the platform — process must be honest about this in training and in supervisor UI (missing work → exception workflow, not fake completion).

### 5.5 Policy / assignment revocation while queued

- On sync, server re-evaluates authority and state. Queued Class B commands against revoked assignment → CONFLICT or REJECTED, never silent success.
- Client policy cache expiry: Class B actions disabled when `policy_fetched_at` older than envelope; Class A remain.

---

## 6. UX copy principles

1. Always distinguish **device-saved** vs **server-confirmed**.
2. Every failure states **what happened** and **what the worker can do next**.
3. No "Error 500" / "Sync failed" alone.
4. Reason codes map to short English (and later Swahili-ready keys) — not raw enum dumps.
5. Do not shame the worker ("you have unsynced fraud risk"); do not hide risk ("all good!") when not confirmed.

---

## 7. Acceptance criteria (must be testable)

| ID | Criterion |
|---|---|
| PS-1 | Global chrome shows accurate non-terminal command count after hard app kill + relaunch, with network still down. |
| PS-2 | After SubmitWork QUEUED, navigating to any screen still shows device-saved vs server status; no bare "Saved." |
| PS-3 | CONFLICT appears in Needs attention without requiring a special debug menu; worker can open reason + next action. |
| PS-4 | Manual "Try now" on a RETRYABLE_FAILURE does not create a second idempotency key or duplicate server effect. |
| PS-5 | End-of-day interstitial blocks casual dismissal when CONFLICT or REJECTED exist. |
| PS-6 | Ops console shows >8h backlog for a simulated worker; alert fires on zero ACCEPTED for a full shift. |
| PS-7 | Quota full → explicit storage error in Sync Center; no silent command drop (property/integration test). |
| PS-8 | Background sync never required for correctness: automated test kills browser mid-queue, reopens later, confirms no loss/duplication. |

---

## 8. Explicitly out of scope (Phase 1)

- Push-notification campaigns to workers for every conflict
- SMS fallback sync
- Multi-device merge UI for the same actor (conflict path → review covers the material case)
- Guaranteed OS-level background execution (PWA limitation; native escape hatch if field evidence demands it)
