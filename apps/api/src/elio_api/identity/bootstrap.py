from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.authz.permissions import ALL_PERMISSIONS, ROLE_BUNDLES
from elio_api.identity.models import (
    Actor,
    ActorRole,
    Organisation,
    Permission,
    Role,
    RolePermission,
    Tenant,
)
from elio_api.identity.passwords import hash_password


async def ensure_permission_catalog(session: AsyncSession) -> None:
    for code in sorted(ALL_PERMISSIONS):
        existing = await session.get(Permission, code)
        if existing is None:
            session.add(Permission(code=code, description=code))


async def provision_tenant(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    create_roles: bool = True,
    seed_demo_users: bool = True,
) -> Tenant:
    """Create a tenant, default roles, hospital templates, and optional demo users."""
    await ensure_permission_catalog(session)
    tenant = Tenant(slug=slug, name=name, status="active")
    session.add(tenant)
    await session.flush()

    if create_roles:
        for role_name, perms in ROLE_BUNDLES.items():
            role = Role(tenant_id=tenant.id, name=role_name, description=role_name)
            session.add(role)
            await session.flush()
            for code in sorted(perms):
                session.add(RolePermission(role_id=role.id, permission_code=code))

    from elio_api.work.template_service import seed_default_tenant_templates

    await seed_default_tenant_templates(
        session, tenant_id=tenant.id, created_by="system-bootstrap"
    )

    if seed_demo_users:
        sup = await create_actor(
            session,
            tenant_id=tenant.id,
            external_subject=f"local|{slug}|supervisor",
            email=f"supervisor@{slug}.test",
            display_name="Demo Supervisor",
            role_names=["supervisor"],
        )
        worker = await create_actor(
            session,
            tenant_id=tenant.id,
            external_subject=f"local|{slug}|worker",
            email=f"worker@{slug}.test",
            display_name="Demo Worker",
            role_names=["field_worker"],
        )
        sup.password_hash = hash_password("SupervisorDev123!")
        worker.password_hash = hash_password("WorkerDev123!")
        await session.flush()

    return tenant


async def create_actor(
    session: AsyncSession,
    *,
    tenant_id: str,
    external_subject: str,
    email: str,
    display_name: str,
    role_names: list[str],
    organisation_id: str | None = None,
    password: str | None = None,
) -> Actor:
    actor = Actor(
        tenant_id=tenant_id,
        organisation_id=organisation_id,
        external_subject=external_subject,
        email=email.lower().strip(),
        display_name=display_name,
        status="active",
        password_hash=hash_password(password) if password else None,
    )
    session.add(actor)
    await session.flush()

    for role_name in role_names:
        role = (
            await session.execute(
                select(Role).where(Role.tenant_id == tenant_id, Role.name == role_name)
            )
        ).scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role not found: {role_name}")
        session.add(ActorRole(actor_id=actor.id, role_id=role.id))
    return actor


async def create_organisation(
    session: AsyncSession, *, tenant_id: str, name: str
) -> Organisation:
    org = Organisation(tenant_id=tenant_id, name=name, status="active")
    session.add(org)
    await session.flush()
    return org
