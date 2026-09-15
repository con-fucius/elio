from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from elio_api.authz.permissions import PermissionCode
from elio_api.identity.auth import AuthContext
from elio_api.identity.deps import SessionDep, require_permission
from elio_api.identity.models import Actor, ActorRole, Role

router = APIRouter(prefix="/actors", tags=["actors"])


class ActorRead(BaseModel):
    id: str
    display_name: str
    email: str
    status: str
    roles: list[str]


@router.get("", response_model=list[ActorRead])
async def list_actors(
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.ACTOR_READ))],
) -> list[ActorRead]:
    """Tenant-scoped actor directory for assignment pickers."""
    actors = (
        await session.execute(
            select(Actor)
            .where(Actor.tenant_id == auth.tenant.id, Actor.status == "active")
            .order_by(Actor.display_name.asc())
        )
    ).scalars().all()

    role_map: dict[str, list[str]] = {}
    if actors:
        rows = await session.execute(
            select(ActorRole.actor_id, Role.name)
            .join(Role, Role.id == ActorRole.role_id)
            .where(ActorRole.actor_id.in_([a.id for a in actors]))
        )
        for actor_id, role_name in rows.all():
            role_map.setdefault(actor_id, []).append(role_name)

    return [
        ActorRead(
            id=a.id,
            display_name=a.display_name,
            email=a.email,
            status=a.status,
            roles=sorted(role_map.get(a.id, [])),
        )
        for a in actors
    ]
