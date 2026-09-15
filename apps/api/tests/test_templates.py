import uuid

import pytest
from conftest import TenantFixture
from httpx import AsyncClient
from test_isolation import auth_headers

from elio_api.config import get_settings


@pytest.fixture(autouse=True)
def _relax_abuse(monkeypatch):
    monkeypatch.setattr(get_settings(), "min_execution_seconds", 0)
    monkeypatch.setattr(get_settings(), "min_evidence_bytes", 1)


async def test_templates_seeded_for_tenant(client: AsyncClient, tenants: TenantFixture) -> None:
    res = await client.get(
        "/api/v1/templates",
        headers=auth_headers(client, tenants, who="supervisor"),
    )
    assert res.status_code == 200
    types = {t["work_type"] for t in res.json()}
    assert "facility_inspection" in types
    assert "equipment_service" in types


async def test_create_instantiates_template_tasks(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Inspection with checklist",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert create.status_code == 201
    work_id = create.json()["work_item_id"]

    tasks = await client.get(
        f"/api/v1/work-items/{work_id}/tasks",
        headers=auth_headers(client, tenants, who="supervisor"),
    )
    assert tasks.status_code == 200
    rows = tasks.json()
    assert len(rows) >= 3
    assert any(t["key"] == "visual_check" for t in rows)
    assert all(t["status"] == "PENDING" for t in rows)


async def test_submit_blocked_until_tasks_and_evidence(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Guarded submit",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    headers_sup = auth_headers(client, tenants, who="supervisor")
    headers_w = auth_headers(client, tenants, who="worker")

    for path, who, extra in [
        ("/release", "supervisor", {}),
        ("/assign", "supervisor", {"assignee_actor_id": tenants.worker_id}),
        ("/accept", "worker", {}),
        ("/start", "worker", {}),
    ]:
        res = await client.post(
            f"/api/v1/work-items/{work_id}{path}",
            headers=headers_sup if who == "supervisor" else headers_w,
            json={"idempotency_key": str(uuid.uuid4()), **extra},
        )
        assert res.status_code == 200, res.text

    # Submit too early
    early = await client.post(
        f"/api/v1/work-items/{work_id}/submit",
        headers=headers_w,
        json={"idempotency_key": str(uuid.uuid4()), "reason": ""},
    )
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "TEMPLATE_INCOMPLETE"

    # Complete required tasks
    tasks = (
        await client.get(
            f"/api/v1/work-items/{work_id}/tasks", headers=headers_w
        )
    ).json()
    for t in tasks:
        if not t["required"]:
            continue
        field_values = {}
        for f in t.get("fields") or []:
            if f.get("type") == "choice":
                field_values[f["key"]] = (f.get("options") or ["n/a"])[0]
            else:
                field_values[f["key"]] = "test"
        # evidence for visual_check
        if t["key"] == "visual_check":
            reg = await client.post(
                f"/api/v1/work-items/{work_id}/evidence",
                headers=headers_w,
                json={
                    "work_item_id": work_id,
                    "evidence_type": "photo",
                    "work_task_id": t["id"],
                },
            )
            assert reg.status_code == 201, reg.text
            payload = b"checklist-photo"
            put = await client.put(
                f"/api/v1/evidence/{reg.json()['id']}/content",
                headers={**headers_w, "Content-Type": "image/jpeg"},
                content=payload,
            )
            assert put.status_code == 200, put.text

        done = await client.post(
            f"/api/v1/work-items/{work_id}/tasks/{t['id']}/complete",
            headers=headers_w,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "notes": "done",
                "field_values": field_values,
            },
        )
        assert done.status_code == 200, done.text

    submit = await client.post(
        f"/api/v1/work-items/{work_id}/submit",
        headers=headers_w,
        json={"idempotency_key": str(uuid.uuid4()), "reason": ""},
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "SUBMITTED"


async def test_required_task_cannot_be_skipped(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "equipment_service",
            "title": "Skip guard",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    headers_sup = auth_headers(client, tenants, who="supervisor")
    headers_w = auth_headers(client, tenants, who="worker")
    for path, who, extra in [
        ("/release", "supervisor", {}),
        ("/assign", "supervisor", {"assignee_actor_id": tenants.worker_id}),
        ("/accept", "worker", {}),
        ("/start", "worker", {}),
    ]:
        await client.post(
            f"/api/v1/work-items/{work_id}{path}",
            headers=headers_sup if who == "supervisor" else headers_w,
            json={"idempotency_key": str(uuid.uuid4()), **extra},
        )
    tasks = (await client.get(f"/api/v1/work-items/{work_id}/tasks", headers=headers_w)).json()
    required = next(t for t in tasks if t["required"])
    skip = await client.post(
        f"/api/v1/work-items/{work_id}/tasks/{required['id']}/skip",
        headers=headers_w,
        json={"idempotency_key": str(uuid.uuid4())},
    )
    assert skip.status_code == 409
    assert skip.json()["detail"]["code"] == "SKIP_NOT_ALLOWED"
