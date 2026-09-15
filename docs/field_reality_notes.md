# Field worker reality notes (Kenya)

**Purpose:** How the product must behave under real field conditions—not just green tests.  
**Audience:** Anyone changing templates, UX, or anti-abuse rules.

---

## Shared reality (all three verticals)

| Reality | Design implication |
|---------|-------------------|
| Intermittent 3G / no signal for hours | Local queue + Send; never block work on network |
| Cheap Android, small screens, one hand | Large primary actions; step-by-step checklist; few controls per screen |
| Power cuts / battery death | Durable IndexedDB; survive app kill |
| Worker distrust of “another app” | Fewer screens; clear next action; no admin jargon |
| Pressure to hit targets | Exception path must be easy; fraud controls must not force fake completes |
| Language | Prefer plain English; Swahili keys later without redesign |

---

## Health field workers

**Who:** Facility support, biomedical technicians, inspectors (non-clinical Phase 1).  
**Not:** Clinical decisions, patient records, EMR.

| Do | Do not |
|----|--------|
| Photo of equipment / room / area | Patient faces, names, clinical notes |
| “Condition: good/fair/poor” | Diagnosis language |
| Serial / asset photo | Casual patient data on free text |
| Arrive → photo → findings → follow-up | Assume every visit is clinical |

**Resilience:** Site closed, generator down, ward too busy → **I cannot continue** (no_access / unsafe), not silent complete.  
**Fraud:** Reusing one room photo across jobs is rejected (checksum). Completing in under the duration floor is rejected.

---

## Marketing field workers

**Who:** Reps, merchandisers, promoters visiting outlets.

| Do | Do not |
|----|--------|
| Right outlet, activity type, short outcome | Unnecessary customer personal data |
| Photo only when the job asks | Stalk GPS / continuous tracking |
| Order / stock as typed outcome | Duplicate order ledgers in Elio |

**Reality:** Shop closed, owner hostile, stock day wrong → exception, not fabricated “visit complete.”  
**Product note:** Offline + GPS already expected in Kenya SFA; Elio wins on **control + audit**, not “another form.”

---

## Debt collection field workers

**Who:** Authorised recovery agents for a legitimate creditor.

| Do | Do not |
|----|--------|
| Case ref + allowed action before contact | Contact references / family lists |
| Channel + result + who you spoke to (role) | Threats, shaming, public disclosure |
| Promise / dispute / close as next step | Harassment loops |

**Reality:** Wrong number, wrong house, dispute raised → record and escalate. System must make abuse hard (templates, review, audit).  
**Regulatory:** Conduct rules depend on the principal and activity—legal classification before production collections volume.

---

## Anti-abuse (applies everywhere)

1. Exception outcome **after** a reported block  
2. Photo reuse window  
3. Minimum photo size  
4. Minimum time from start → completed  

Tune only with ops agreement. Tests set floors to 0; production keeps defaults.

---

## What “better” means for the field

Not prettier UI. **Fewer wrong taps, clearer next action, honest device vs server state, and a way to say “I cannot do this” without lying.**
