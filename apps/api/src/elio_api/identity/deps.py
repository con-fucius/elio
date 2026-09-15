from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.authz.permissions import PermissionCode
from elio_api.authz.service import actor_has_permission
from elio_api.config import get_settings
from elio_api.db.session import get_session
from elio_api.identity.auth import (
    AuthContext,
    JwtTokenVerifier,
    TokenError,
    forbidden,
    load_auth_context,
    unauthorized,
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_auth_context(request: Request, session: SessionDep) -> AuthContext:
    settings = get_settings()
    if not settings.auth_enabled:
        raise RuntimeError("Unauthenticated access is not supported; set ELIO_AUTH_ENABLED=true")

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise unauthorized("Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = JwtTokenVerifier(settings).verify(token)
        return await load_auth_context(session, claims)
    except TokenError as exc:
        raise unauthorized(str(exc)) from exc


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]


def require_permission(
    permission: PermissionCode,
) -> Callable[..., Awaitable[AuthContext]]:
    async def checker(auth: AuthDep, session: SessionDep) -> AuthContext:
        allowed = await actor_has_permission(
            session, actor_id=auth.actor.id, tenant_id=auth.tenant.id, permission=permission.value
        )
        if not allowed:
            raise forbidden("PERMISSION_DENIED", f"Missing permission: {permission.value}")
        return auth

    return checker
