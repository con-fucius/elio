from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.authz.service import actor_permission_codes
from elio_api.config import Settings, get_settings
from elio_api.identity.deps import AuthDep, SessionDep
from elio_api.identity.models import Actor, Session, Tenant
from elio_api.identity.passwords import verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    actor_id: str
    tenant_id: str
    display_name: str
    email: str
    roles: list[str]
    permissions: list[str]


class MeResponse(BaseModel):
    actor_id: str
    tenant_id: str
    tenant_slug: str
    display_name: str
    email: str
    roles: list[str]
    permissions: list[str]
    jti: str


class LogoutResponse(BaseModel):
    status: str = "revoked"


def _issue_token(
    settings: Settings, actor: Actor, tenant: Tenant, jti: str
) -> tuple[str, datetime]:
    if not settings.jwt_private_key_pem:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "LOGIN_NOT_CONFIGURED",
                "message": "jwt_private_key_pem is not configured on the server",
                "retryable": False,
            },
        )
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.access_token_ttl_seconds)
    payload: dict[str, Any] = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": actor.external_subject,
        "elio_actor_id": actor.id,
        "elio_tenant_id": tenant.id,
        "iat": now,
        "exp": exp,
        "jti": jti,
    }
    token = jwt.encode(
        payload,
        settings.jwt_private_key_pem,
        algorithm=settings.jwt_algorithm,
    )
    return token, exp


async def _roles_for(session: AsyncSession, actor_id: str, tenant_id: str) -> list[str]:
    from elio_api.identity.models import ActorRole, Role

    rows = await session.execute(
        select(Role.name)
        .join(ActorRole, ActorRole.role_id == Role.id)
        .where(ActorRole.actor_id == actor_id, Role.tenant_id == tenant_id)
        .distinct()
    )
    return sorted({r[0] for r in rows.all()})


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginBody, session: SessionDep) -> LoginResponse:
    settings = get_settings()
    if not settings.allow_password_login:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PASSWORD_LOGIN_DISABLED",
                "message": "Password login is disabled; use the identity provider",
                "retryable": False,
            },
        )

    result = await session.execute(
        select(Actor).where(Actor.email == body.email.lower().strip())
    )
    actor = result.scalar_one_or_none()
    if (
        actor is None
        or actor.status != "active"
        or not actor.password_hash
        or not verify_password(body.password, actor.password_hash)
    ):
        # Same error for unknown user / bad password
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid email or password",
                "retryable": False,
            },
        )

    tenant = await session.get(Tenant, actor.tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "TENANT_INACTIVE",
                "message": "Tenant is not active",
                "retryable": False,
            },
        )

    jti = str(uuid.uuid4())
    now = datetime.now(UTC)
    session.add(
        Session(
            tenant_id=tenant.id,
            actor_id=actor.id,
            jti=jti,
            issued_at=now,
            expires_at=now + timedelta(seconds=settings.access_token_ttl_seconds),
        )
    )
    token, _exp = _issue_token(settings, actor, tenant, jti)
    await session.commit()

    roles = await _roles_for(session, actor.id, tenant.id)
    permissions = sorted(
        await actor_permission_codes(session, actor_id=actor.id, tenant_id=tenant.id)
    )
    return LoginResponse(
        access_token=token,
        expires_in=settings.access_token_ttl_seconds,
        actor_id=actor.id,
        tenant_id=tenant.id,
        display_name=actor.display_name,
        email=actor.email,
        roles=roles,
        permissions=permissions,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(auth: AuthDep, session: SessionDep) -> LogoutResponse:
    row = await session.scalar(select(Session).where(Session.jti == auth.jti))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.commit()
    return LogoutResponse()


@router.get("/me", response_model=MeResponse)
async def me(auth: AuthDep, session: SessionDep) -> MeResponse:
    roles = await _roles_for(session, auth.actor.id, auth.tenant.id)
    permissions = sorted(
        await actor_permission_codes(
            session, actor_id=auth.actor.id, tenant_id=auth.tenant.id
        )
    )
    return MeResponse(
        actor_id=auth.actor.id,
        tenant_id=auth.tenant.id,
        tenant_slug=auth.tenant.slug,
        display_name=auth.actor.display_name,
        email=auth.actor.email,
        roles=roles,
        permissions=permissions,
        jti=auth.jti,
    )
