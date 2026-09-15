# ADR-001: Documentation authority stack and Phase-0 gate

**Status:** Accepted  
**Date:** 2026-05 (working session)  
**Deciders:** Project owner + collaborating engineer  

## Context

The repo accumulated overlapping baselines: `implementation_contract.txt`, `brainstorm_parent.md`, and R1–R9 in `brainstorm_child.txt`. Rules were lifted from another project (`DataWorkbench`). Without an explicit precedence rule, implementation would drift or cherry-pick whichever document was open.

## Decision

1. `docs/canonical_baseline.md` is the top of the authority stack.
2. Numbered ADRs sit below it and record irreversible or expensive-to-reverse decisions.
3. Domain artifacts (glossary, state machines, pending-sync design, stress-test matrix) sit below ADRs.
4. `implementation_contract.txt` is architecture reference, not Phase-0 authority.
5. R1–R9 and parent brainstorm are historical reasoning. They are mined for nuance, never implemented from directly.
6. Phase 0 (glossary, state machines, stress-test) completes before monorepo skeleton and before any API surface.

## Consequences

- New contradictions are resolved by editing the baseline or writing an ADR — not by informal agreement.
- R1–R9 will atrophy as a reference; that is intended.
- Rules live in `rules.txt` and reflect Elio only.
