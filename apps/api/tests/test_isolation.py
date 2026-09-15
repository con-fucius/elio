import uuid

from conftest import TenantFixture, make_token
from httpx import AsyncClient


def auth_headers(client: AsyncClient, tenants: TenantFixture, *, who: str) -> dict[str, str]:
    private_pem = client.private_pem  # type: ignore[attr-defined]
    if who == "supervisor":
        token = make_token(
            private_pem,
            actor_id=tenants.supervisor_id,
            tenant_id=tenants.tenant_id,
            subject=tenants.supervisor_sub,
        )
    elif who == "worker":
        token = make_token(
            private_pem,
            actor_id=tenants.worker_id,
            tenant_id=tenants.tenant_id,
            subject=tenants.worker_sub,
        )
    elif who == "other_worker":
        token = make_token(
            private_pem,
            actor_id=tenants.other_worker_id,
            tenant_id=tenants.other_tenant_id,
            subject=tenants.other_worker_sub,
        )
    else:
        raise ValueError(who)
    return {"Authorization": f"Bearer {token}"}


async def test_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/v1/work-items")
    assert res.status_code == 401


async def test_cross_tenant_read_denied(client: AsyncClient, tenants: TenantFixture) -> None:
    # Supervisor in tenant A creates work
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Alpha only",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert create.status_code == 201
    work_id = create.json()["work_item_id"]

    # Worker in tenant B must not see it
    res = await client.get(
        f"/api/v1/work-items/{work_id}",
        headers=auth_headers(client, tenants, who="other_worker"),
    )
    assert res.status_code == 404

    # Tenant B list must be empty of A's items
    listing = await client.get(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="other_worker"),
    )
    assert listing.status_code == 200
    assert all(item["tenant_id"] == tenants.other_tenant_id for item in listing.json())


async def test_cross_tenant_assign_denied(client: AsyncClient, tenants: TenantFixture) -> None:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Assign target",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]

    res = await client.post(
        f"/api/v1/work-items/{work_id}/assign",
        headers=auth_headers(client, tenants, who="other_worker"),
        json={
            "idempotency_key": str(uuid.uuid4()),
            "assignee_actor_id": tenants.other_worker_id,
        },
    )
    assert res.status_code == 404


async def test_permission_denied_for_worker_create(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    res = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="worker"),
        json={
            "work_type": "facility_inspection",
            "title": "Nope",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert res.status_code == 403
