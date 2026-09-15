"""Seed local Postgres with a demo tenant + users for manual UI login."""

import asyncio

from sqlalchemy import select

from elio_api.config import get_settings
from elio_api.db.session import SessionLocal
from elio_api.identity.bootstrap import provision_tenant
from elio_api.identity.models import Tenant


async def main() -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(Tenant).where(Tenant.slug == "alpha-hospital"))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"tenant exists: {existing.slug} ({existing.id})")
            return
        tenant = await provision_tenant(
            session, slug="alpha-hospital", name="Alpha Hospital"
        )
        await session.commit()
        print(f"seeded tenant {tenant.slug} ({tenant.id})")


if __name__ == "__main__":
    asyncio.run(main())
