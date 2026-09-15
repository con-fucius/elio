"""Backfill missing baseline templates on existing tenants (idempotent)."""

import asyncio

from sqlalchemy import select

from elio_api.db.session import SessionLocal
from elio_api.identity.models import Tenant
from elio_api.work.template_service import seed_default_tenant_templates


async def main() -> None:
    async with SessionLocal() as session:
        tenants = (await session.execute(select(Tenant).where(Tenant.status == "active"))).scalars().all()
        for tenant in tenants:
            created = await seed_default_tenant_templates(
                session, tenant_id=tenant.id, created_by="system-backfill"
            )
            await session.commit()
            names = [t.work_type for t in created]
            print(f"{tenant.slug}: added {names or '(none new)'}")


if __name__ == "__main__":
    asyncio.run(main())
