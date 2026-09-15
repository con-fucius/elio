from conftest import TenantFixture
from httpx import AsyncClient
from test_isolation import auth_headers


async def test_actors_list_supervisor(client: AsyncClient, tenants: TenantFixture) -> None:
    res = await client.get(
        "/api/v1/actors",
        headers=auth_headers(client, tenants, who="supervisor"),
    )
    assert res.status_code == 200
    rows = res.json()
    ids = {r["id"] for r in rows}
    assert tenants.worker_id in ids
    assert tenants.supervisor_id in ids


async def test_actors_list_worker_forbidden(client: AsyncClient, tenants: TenantFixture) -> None:
    # field_worker role lacks actor.read
    res = await client.get(
        "/api/v1/actors",
        headers=auth_headers(client, tenants, who="worker"),
    )
    assert res.status_code == 403
