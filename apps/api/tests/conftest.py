import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from elio_api.config import get_settings
from elio_api.db import Base
from elio_api.db.session import get_session
from elio_api.identity.bootstrap import create_actor, create_organisation, provision_tenant
from elio_api.identity.models import Session
from elio_api.main import create_app

TEST_DATABASE_URL = os.environ.get("ELIO_TEST_DATABASE_URL")
POSTGRES_IMAGE = os.environ.get("ELIO_TEST_POSTGRES_IMAGE", "postgres:16-alpine")


def _to_asyncpg_url(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


@pytest.fixture
async def db_engine():
    container = None
    if TEST_DATABASE_URL:
        url = TEST_DATABASE_URL
    else:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer(POSTGRES_IMAGE)
        container.with_env("POSTGRES_USER", "elio")
        container.with_env("POSTGRES_PASSWORD", "elio")
        container.with_env("POSTGRES_DB", "elio")
        container.start()
        url = _to_asyncpg_url(container.get_connection_url())

    engine = create_async_engine(url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    if container is not None:
        container.stop()


@pytest.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@dataclass
class TenantFixture:
    tenant_id: str
    org_id: str
    supervisor_id: str
    worker_id: str
    supervisor_sub: str
    worker_sub: str
    other_tenant_id: str
    other_worker_id: str
    other_worker_sub: str


@pytest.fixture
async def tenants(session_factory) -> TenantFixture:
    async with session_factory() as s:
        t1 = await provision_tenant(s, slug="alpha-hospital", name="Alpha Hospital")
        org = await create_organisation(s, tenant_id=t1.id, name="Ward Ops")
        sup = await create_actor(
            s,
            tenant_id=t1.id,
            external_subject="idp|sup-alpha",
            email="sup@alpha.test",
            display_name="Sup Alpha",
            role_names=["supervisor"],
            organisation_id=org.id,
        )
        worker = await create_actor(
            s,
            tenant_id=t1.id,
            external_subject="idp|worker-alpha",
            email="worker@alpha.test",
            display_name="Worker Alpha",
            role_names=["field_worker"],
            organisation_id=org.id,
        )
        t2 = await provision_tenant(s, slug="beta-hospital", name="Beta Hospital")
        other = await create_actor(
            s,
            tenant_id=t2.id,
            external_subject="idp|worker-beta",
            email="worker@beta.test",
            display_name="Worker Beta",
            role_names=["field_worker", "supervisor"],
        )
        await s.commit()
        return TenantFixture(
            tenant_id=t1.id,
            org_id=org.id,
            supervisor_id=sup.id,
            worker_id=worker.id,
            supervisor_sub=sup.external_subject,
            worker_sub=worker.external_subject,
            other_tenant_id=t2.id,
            other_worker_id=other.id,
            other_worker_sub=other.external_subject,
        )


def make_token(
    private_pem: str,
    *,
    actor_id: str,
    tenant_id: str,
    subject: str,
    jti: str | None = None,
    ttl_seconds: int = 900,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": subject,
        "elio_actor_id": actor_id,
        "elio_tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": jti or str(uuid.uuid4()),
    }
    return jwt.encode(payload, private_pem, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def client(session_factory, rsa_keypair, tenants, monkeypatch, tmp_path):
    private_pem, public_pem = rsa_keypair
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_public_key_pem", public_pem)
    monkeypatch.setattr(settings, "jwt_private_key_pem", private_pem)
    monkeypatch.setattr(settings, "allow_password_login", True)
    monkeypatch.setattr(settings, "evidence_root", str(tmp_path / "evidence"))
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    cached = get_settings()
    monkeypatch.setattr(cached, "jwt_public_key_pem", public_pem)
    monkeypatch.setattr(cached, "jwt_private_key_pem", private_pem)
    monkeypatch.setattr(cached, "auth_enabled", True)
    monkeypatch.setattr(cached, "allow_password_login", True)
    monkeypatch.setattr(cached, "evidence_root", str(tmp_path / "evidence"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.private_pem = private_pem  # type: ignore[attr-defined]
        ac.tenants = tenants  # type: ignore[attr-defined]
        yield ac


async def register_session(
    session: AsyncSession, *, tenant_id: str, actor_id: str, jti: str, ttl_seconds: int = 900
) -> None:
    now = datetime.now(UTC)
    session.add(
        Session(
            tenant_id=tenant_id,
            actor_id=actor_id,
            jti=jti,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    await session.commit()
