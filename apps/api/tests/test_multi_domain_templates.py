import uuid

import pytest
from conftest import TenantFixture
from httpx import AsyncClient
from test_isolation import auth_headers
from test_journeys import _cmd, _login

from elio_api.config import get_settings


@pytest.fixture(autouse=True)
def _relax_abuse(monkeypatch):
    monkeypatch.setattr(get_settings(), "min_execution_seconds", 0)
    monkeypatch.setattr(get_settings(), "min_evidence_bytes", 1)


async def test_templates_include_all_domains(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    res = await client.get(
        "/api/v1/templates",
        headers=auth_headers(client, tenants, who="supervisor"),
    )
    assert res.status_code == 200
    by_type = {t["work_type"]: t for t in res.json()}
    assert "facility_inspection" in by_type
    assert "equipment_service" in by_type
    assert "outlet_visit" in by_type
    assert "collection_contact" in by_type
    assert by_type["outlet_visit"]["domain"] == "marketing"
    assert by_type["collection_contact"]["domain"] == "collections"
    assert by_type["collection_contact"]["review_required"] is True
    assert by_type["outlet_visit"]["review_required"] is False


async def test_marketing_outlet_visit_workflow(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    sup = await _login(client, "supervisor@alpha-hospital.test", "SupervisorDev123!")
    worker = await _login(client, "worker@alpha-hospital.test", "WorkerDev123!")

    create = await client.post(
        "/api/v1/work-items",
        headers={"Authorization": sup["Authorization"]},
        json={
            "work_type": "outlet_visit",
            "title": "Kiosk visit Nairobi",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert create.status_code == 201
    work_id = create.json()["work_item_id"]
    await _cmd(client, sup, work_id, "/release")
    await _cmd(client, sup, work_id, "/assign", assignee_actor_id=worker["actor_id"])
    await _cmd(client, worker, work_id, "/accept")
    await _cmd(client, worker, work_id, "/start")

    tasks = (
        await client.get(
            f"/api/v1/work-items/{work_id}/tasks",
            headers={"Authorization": worker["Authorization"]},
        )
    ).json()
    activity = next(t for t in tasks if t["key"] == "activity")
    field_values = {"activity_type": "stock_check", "outcome_notes": "Shelf full"}
    done = await _cmd(
        client,
        worker,
        work_id,
        f"/tasks/{activity['id']}/complete",
        field_values=field_values,
        notes="",
    )
    assert done.status_code == 200, done.text

    for t in tasks:
        if not t["required"] or t["key"] == "activity":
            continue
        if t.get("status") == "COMPLETED":
            continue
        res = await _cmd(client, worker, work_id, f"/tasks/{t['id']}/complete")
        assert res.status_code == 200, res.text

    submit = await _cmd(client, worker, work_id, "/submit")
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "SUBMITTED"


async def test_collections_template_seeded_and_fields(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    res = await client.get(
        "/api/v1/templates",
        headers=auth_headers(client, tenants, who="supervisor"),
    )
    coll = next(t for t in res.json() if t["work_type"] == "collection_contact")
    keys = {t["key"] for t in coll["tasks"]}
    assert keys == {"verify_context", "contact_attempt", "record_followup"}
    contact = next(t for t in coll["tasks"] if t["key"] == "contact_attempt")
    field_keys = {f["key"] for f in contact.get("fields") or []}
    assert field_keys == {"channel", "result", "spoke_to"}
