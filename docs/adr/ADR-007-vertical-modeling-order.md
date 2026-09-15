# ADR-007: Vertical modeling order — hospital first as constraint vehicle

**Status:** Accepted  
**Date:** 2026-05 (working session)  

## Context

Earlier documents contradicted each other: contract preferred hospital first "to force privacy early"; R2/R9 preferred marketing first "for lowest regulatory burden." User direction: both hospital and marketing are priority verticals; neither is commercially ranked; exhaustive implementation applies to each; Phase 0 needs one vehicle to draft glossary and state machines against.

## Decision

- **No commercial or delivery ranking** between hospital and marketing.
- **Phase 0 modeling vehicle is hospital** because its constraint set (health-data boundaries, purpose limitation, minimum-necessary context, authority) is denser and will expose gaps in the core model earlier.
- Collections remains in scope, deferred pending legal classification against a real deploying entity.
- When hospital and marketing are actually built, each gets exhaustive rigorous implementation. Modeling hospital first does not ship-gate marketing.

## Consequences

- Glossary and state machines in Phase 0 are hospital-flavored; marketing deltas are noted as domain-profile extensions, not a second core model.
- If hospital constraints turn out unrepresentable without EMR-like scope, the model fails the test — that is the point of using hospital as the vehicle.
