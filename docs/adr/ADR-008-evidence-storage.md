# ADR-008: Evidence object storage — no AWS S3 in Phase 1

**Status:** Accepted  
**Date:** 2026-05 (working session)  

## Context

Contract originally pointed at “S3-compatible object storage.” That usually means AWS S3 and a paid AWS account. Phase 1 has no AWS budget. Evidence still needs durable blob storage with integrity (checksum) and tenant scoping.

## Decision

**Phase 1 evidence storage stays the local content-addressed store** already implemented:

- `LocalEvidenceStore` under `ELIO_EVIDENCE_ROOT` (default `var/evidence`)
- Layout: `{tenant_id}/{sha256}` 
- Atomic write via `.partial` then rename
- Domain only stores `storage_reference` (tenant/checksum key), not a vendor URL

This is not a temporary stub: it is the real pilot backend. Swapping later means changing the store adapter only.

### When we outgrow local disk (multi-node, backups, partner hosting)

Prefer in this order — **all S3-API compatible or simple**, none require AWS:

| Option | Cost model | Why consider |
|---|---|---|
| **Cloudflare R2** | Free egress; storage free tier then cheap | S3 API; no egress bill trap |
| **Backblaze B2** | Cheap storage; free egress to certain partners | S3-compatible API |
| **MinIO (self-host)** | Free OSS; runs on a VPS we control | Full S3 API without AWS account |
| **Wasabi / Hetzner / etc.** | Paid but predictable | Only if partner requires managed object store |

**Not chosen for Phase 1:** AWS S3 (account/billing/complexity), GCP-only buckets (same lock-in problem), “upload to Postgres BYTEA” (wrong tool at any real volume).

## Consequences

- Pilot can run on one host + Postgres with no cloud storage bill.
- Multi-instance horizontal scale later requires either shared disk or one of the adapters above.
- Evidence integrity still enforced by SHA-256 + download verification.
