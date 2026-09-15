from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.identity.models import ActorRole, Role, RolePermission


async def actor_has_permission(
    session: AsyncSession, *, actor_id: str, tenant_id: str, permission: str
) -> bool:
    """Server-side authorization. Tenant is always scoped. Never trust client role claims."""
    result = await session.execute(
        select(RolePermission.permission_code)
        .join(Role, Role.id == RolePermission.role_id)
        .join(ActorRole, ActorRole.role_id == Role.id)
        .where(
            ActorRole.actor_id == actor_id,
            Role.tenant_id == tenant_id,
            RolePermission.permission_code == permission,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def actor_permission_codes(
    session: AsyncSession, *, actor_id: str, tenant_id: str
) -> set[str]:
    result = await session.execute(
        select(RolePermission.permission_code)
        .join(Role, Role.id == RolePermission.role_id)
        .join(ActorRole, ActorRole.role_id == Role.id)
        .where(ActorRole.actor_id == actor_id, Role.tenant_id == tenant_id)
        .distinct()
    )
    return {row[0] for row in result.all()}
