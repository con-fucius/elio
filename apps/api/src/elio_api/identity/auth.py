from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.config import Settings
from elio_api.identity.models import Actor, Session, Tenant


@dataclass(frozen=True, slots=True)
class AuthContext:
    actor: Actor
    tenant: Tenant
    jti: str


class TokenError(Exception):
    """Token failed verification or is unusable."""


class JwtTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def verify(self, token: str) -> dict[str, object]:
        if not self._settings.jwt_public_key_pem:
            raise TokenError("jwt_public_key_pem is not configured")
        try:
            claims = jwt.decode(
                token,
                self._settings.jwt_public_key_pem,
                algorithms=[self._settings.jwt_algorithm],
                issuer=self._settings.jwt_issuer,
                audience=self._settings.jwt_audience,
                options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError(str(exc)) from exc
        return claims


async def load_auth_context(session: AsyncSession, claims: dict[str, object]) -> AuthContext:
    actor_id = claims.get("elio_actor_id")
    jti = claims.get("jti")
    if not isinstance(actor_id, str) or not isinstance(jti, str):
        raise TokenError("missing elio_actor_id or jti claim")

    actor = await session.get(Actor, actor_id)
    if actor is None or actor.status != "active":
        raise TokenError("actor not found or disabled")

    tenant = await session.get(Tenant, actor.tenant_id)
    if tenant is None or tenant.status != "active":
        raise TokenError("tenant not found or not active")

    token_tenant = claims.get("elio_tenant_id")
    if isinstance(token_tenant, str) and token_tenant != actor.tenant_id:
        raise TokenError("tenant claim does not match actor")

    session_row = await session.scalar(select(Session).where(Session.jti == jti))
    if session_row is not None:
        if session_row.revoked_at is not None:
            raise TokenError("session revoked")
        if session_row.actor_id != actor.id:
            raise TokenError("session actor mismatch")
        if session_row.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
            raise TokenError("session expired")

    return AuthContext(actor=actor, tenant=tenant, jti=jti)


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHENTICATED", "message": detail, "retryable": False},
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message, "retryable": False},
    )
