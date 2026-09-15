"""Full user journeys: happy path and sad paths for hospital facility inspection."""

import hashlib
import uuid

import pytest
from conftest import TenantFixture
from httpx import AsyncClient
from test_isolation import auth_headers

from elio_api.config import get_settings


@pytest.fixture(autouse=True)
def _relax_abuse_for_journeys(monkeypatch):
    monkeypatch.setattr(get_settings(), "min_execution_seconds", 0)
    monkeypatch.setattr(get_settings(), "min_evidence_bytes", 1)


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
        "actor_id": body["actor_id"],
    }


def _hdr(headers: dict) -> dict:
    return {"Authorization": headers["Authorization"]}


async def _cmd(client, headers, work_id, path, **body):
    body.setdefault("idempotency_key", str(uuid.uuid4()))
    return await client.post(
        f"/api/v1/work-items/{work_id}{path}", headers=_hdr(headers), json=body
    )


async def test_journey_full_happy_path_with_fields_and_evidence(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    """Happy path and sad paths: create through complete with fields and evidence."""
    sup = await _login(client, "supervisor@alpha-hospital.test", "SupervisorDev123!")
    worker = await _login(client, "worker@alpha-hospital.test", "WorkerDev123!")

    create = await client.post(
        "/api/v1/work-items",
        headers=_hdr(sup),
        json={
            "work_type": "facility_inspection",
            "title": "Ward B inspection",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert create.status_code == 201
    work_id = create.json()["work_item_id"]

    edit = await client.patch(
        f"/api/v1/work-items/{work_id}",
        headers=_hdr(sup),
        json={"title": "Ward B — morning inspection"},
    )
    assert edit.status_code == 200

    await _cmd(client, sup, work_id, "/release")
    await _cmd(client, sup, work_id, "/assign", assignee_actor_id=worker["actor_id"])
    await _cmd(client, worker, work_id, "/accept")
    await _cmd(client, worker, work_id, "/start")

    tasks = (
        await client.get(f"/api/v1/work-items/{work_id}/tasks", headers=_hdr(worker))
    ).json()
    assert tasks

    for t in tasks:
        if not t["required"]:
            continue
        field_values = {}
        for f in t.get("fields") or []:
            if f.get("type") == "choice":
                field_values[f["key"]] = (f.get("options") or ["n/a"])[0]
            else:
                field_values[f["key"]] = f"answered for {f['key']}"

        save = await client.patch(
            f"/api/v1/work-items/{work_id}/tasks/{t['id']}",
            headers=_hdr(worker),
            json={"notes": "draft note", "field_values": field_values},
        )
        assert save.status_code == 200, save.text

        if "photo" in t.get("required_evidence_types", []):
            reg = await client.post(
                f"/api/v1/work-items/{work_id}/evidence",
                headers=_hdr(worker),
                json={
                    "work_item_id": work_id,
                    "evidence_type": "photo",
                    "work_task_id": t["id"],
                },
            )
            assert reg.status_code == 201
            payload = b"journey-photo-bytes"
            put = await client.put(
                f"/api/v1/evidence/{reg.json()['id']}/content",
                headers={**_hdr(worker), "Content-Type": "image/jpeg"},
                content=payload,
            )
            assert put.status_code == 200

        done = await _cmd(
            client,
            worker,
            work_id,
            f"/tasks/{t['id']}/complete",
            notes="done",
            field_values=field_values,
        )
        assert done.status_code == 200, done.text

    evidence = await client.get(
        f"/api/v1/work-items/{work_id}/evidence", headers=_hdr(worker)
    )
    assert evidence.status_code == 200
    assert len(evidence.json()) >= 1
    eid = evidence.json()[0]["id"]
    dl = await client.get(f"/api/v1/evidence/{eid}/content", headers=_hdr(worker))
    assert dl.status_code == 200
    assert dl.content == b"journey-photo-bytes"

    submit = await _cmd(client, worker, work_id, "/submit", reason="")
    assert submit.status_code == 200
    assert submit.json()["status"] == "SUBMITTED"

    await _cmd(client, sup, work_id, "/review/begin")
    await _cmd(client, sup, work_id, "/review/accept", reason="Looks good")
    final = await client.get(f"/api/v1/work-items/{work_id}", headers=_hdr(sup))
    assert final.json()["status"] == "COMPLETED"


async def test_sad_complete_requires_fields(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    sup = await _login(client, "supervisor@alpha-hospital.test", "SupervisorDev123!")
    worker = await _login(client, "worker@alpha-hospital.test", "WorkerDev123!")
    create = await client.post(
        "/api/v1/work-items",
        headers=_hdr(sup),
        json={
            "work_type": "facility_inspection",
            "title": "Missing fields",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    await _cmd(client, sup, work_id, "/release")
    await _cmd(client, sup, work_id, "/assign", assignee_actor_id=worker["actor_id"])
    await _cmd(client, worker, work_id, "/accept")
    await _cmd(client, worker, work_id, "/start")
    tasks = (
        await client.get(f"/api/v1/work-items/{work_id}/tasks", headers=_hdr(worker))
    ).json()
    findings = next(t for t in tasks if t["key"] == "record_findings")
    bad = await _cmd(
        client,
        worker,
        work_id,
        f"/tasks/{findings['id']}/complete",
        notes="",
        field_values={},
    )
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "FIELDS_REQUIRED"


async def test_sad_edit_after_submit_rejected(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    sup = await _login(client, "supervisor@alpha-hospital.test", "SupervisorDev123!")
    worker = await _login(client, "worker@alpha-hospital.test", "WorkerDev123!")
    create = await client.post(
        "/api/v1/work-items",
        headers=_hdr(sup),
        json={
            "work_type": "facility_inspection",
            "title": "Locked after submit",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    await _cmd(client, sup, work_id, "/release")
    await _cmd(client, sup, work_id, "/assign", assignee_actor_id=worker["actor_id"])
    await _cmd(client, worker, work_id, "/accept")
    await _cmd(client, worker, work_id, "/start")
    await _cmd(
        client,
        worker,
        work_id,
        "/exception",
        reason="no_access|Site closed for the day",
    )
    await _cmd(
        client,
        worker,
        work_id,
        "/submit",
        reason="site closed",
        outcome_type="UNABLE_TO_ACCESS",
    )
    edit = await client.patch(
        f"/api/v1/work-items/{work_id}",
        headers=_hdr(worker),
        json={"title": "too late"},
    )
    assert edit.status_code == 409
    assert edit.json()["detail"]["code"] == "WORK_IMMUTABLE"


async def test_sad_cross_tenant_evidence_denied(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    sup = await _login(client, "supervisor@alpha-hospital.test", "SupervisorDev123!")
    worker = await _login(client, "worker@alpha-hospital.test", "WorkerDev123!")
    other = auth_headers(client, tenants, who="other_worker")
    create = await client.post(
        "/api/v1/work-items",
        headers=_hdr(sup),
        json={
            "work_type": "facility_inspection",
            "title": "Private work",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    await _cmd(client, sup, work_id, "/release")
    await _cmd(client, sup, work_id, "/assign", assignee_actor_id=worker["actor_id"])
    await _cmd(client, worker, work_id, "/accept")
    await _cmd(client, worker, work_id, "/start")
    reg = await client.post(
        f"/api/v1/work-items/{work_id}/evidence",
        headers=_hdr(worker),
        json={"work_item_id": work_id, "evidence_type": "photo"},
    )
    assert reg.status_code == 201
    eid = reg.json()["id"]
    payload = b"secret"
    put = await client.put(
        f"/api/v1/evidence/{eid}/content",
        headers={**_hdr(worker), "Content-Type": "image/jpeg"},
        content=payload,
    )
    assert put.status_code == 200
    assert hashlib.sha256(payload).hexdigest() == put.json()["checksum"]

    den = await client.get(f"/api/v1/evidence/{eid}/content", headers=other)
    assert den.status_code in {403, 404}


async def test_login_logout_me_journey(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "worker@alpha-hospital.test", "password": "WorkerDev123!"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["roles"] == ["field_worker"]
    out = await client.post("/api/v1/auth/logout", headers=headers)
    assert out.status_code == 200
    after = await client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 401
