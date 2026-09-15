from conftest import TenantFixture
from httpx import AsyncClient


async def test_login_success_supervisor(client: AsyncClient, tenants: TenantFixture) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "supervisor@alpha-hospital.test", "password": "SupervisorDev123!"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["display_name"] == "Demo Supervisor"
    assert "supervisor" in body["roles"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "supervisor@alpha-hospital.test"


async def test_login_success_worker(client: AsyncClient, tenants: TenantFixture) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "worker@alpha-hospital.test", "password": "WorkerDev123!"},
    )
    assert res.status_code == 200
    assert "field_worker" in res.json()["roles"]


async def test_login_bad_password(client: AsyncClient, tenants: TenantFixture) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "supervisor@alpha-hospital.test", "password": "wrong"},
    )
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_email(client: AsyncClient, tenants: TenantFixture) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.test", "password": "x"},
    )
    assert res.status_code == 401


async def test_logout_revokes_session(client: AsyncClient, tenants: TenantFixture) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "supervisor@alpha-hospital.test", "password": "SupervisorDev123!"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_ok = await client.get("/api/v1/auth/me", headers=headers)
    assert me_ok.status_code == 200

    out = await client.post("/api/v1/auth/logout", headers=headers)
    assert out.status_code == 200

    me_after = await client.get("/api/v1/auth/me", headers=headers)
    assert me_after.status_code == 401
