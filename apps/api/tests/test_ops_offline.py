"""Ops decisions via sync command batch (same queue as field work)."""

import uuid

from conftest import TenantFixture
from httpx import AsyncClient
from test_journeys import _cmd, _login


async def test_ops_assign_and_review_via_sync(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    sup = await _login(client, "supervisor@alpha-hospital.test", "SupervisorDev123!")
    worker = await _login(client, "worker@alpha-hospital.test", "WorkerDev123!")

    create = await client.post(
        "/api/v1/work-items",
        headers={"Authorization": sup["Authorization"]},
        json={
            "work_type": "facility_inspection",
            "title": "Ops offline path",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]

    # Release via REST then assign/review via sync batch (ops offline model)
    await _cmd(client, sup, work_id, "/release")

    batch = {
        "commands": [
            {
                "command_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
                "command_type": "AssignWork",
                "aggregate_id": work_id,
                "schema_version": 1,
                "client_sequence": 1,
                "payload": {"assignee_actor_id": worker["actor_id"]},
            },
            {
                "command_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
                "command_type": "AcceptAssignment",
                "aggregate_id": work_id,
                "schema_version": 1,
                "client_sequence": 2,
                "payload": {},
            },
            {
                "command_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
                "command_type": "StartWork",
                "aggregate_id": work_id,
                "schema_version": 1,
                "client_sequence": 3,
                "payload": {},
            },
            {
                "command_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
                "command_type": "RaiseException",
                "aggregate_id": work_id,
                "schema_version": 1,
                "client_sequence": 4,
                "payload": {"reason": "no_access|Gate locked"},
            },
            {
                "command_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
                "command_type": "ResolveException",
                "aggregate_id": work_id,
                "schema_version": 1,
                "client_sequence": 5,
                "payload": {"reason": "cleared"},
            },
        ]
    }

    # Assign as supervisor
    res = await client.post(
        "/api/v1/sync/commands",
        headers={"Authorization": sup["Authorization"]},
        json={"commands": batch["commands"][:1]},
    )
    assert res.status_code == 200
    assert res.json()["results"][0]["status"] == "accepted"

    # Worker: accept + start
    res2 = await client.post(
        "/api/v1/sync/commands",
        headers={"Authorization": worker["Authorization"]},
        json={"commands": batch["commands"][1:3]},
    )
    assert res2.status_code == 200
    statuses = [r["status"] for r in res2.json()["results"]]
    assert statuses == ["accepted", "accepted"]

    # Exception + unblock
    res3 = await client.post(
        "/api/v1/sync/commands",
        headers={"Authorization": worker["Authorization"]},
        json={"commands": batch["commands"][3:4]},
    )
    assert res3.json()["results"][0]["status"] == "accepted"

    res4 = await client.post(
        "/api/v1/sync/commands",
        headers={"Authorization": sup["Authorization"]},
        json={"commands": batch["commands"][4:]},
    )
    assert res4.json()["results"][0]["status"] == "accepted"

    item = await client.get(
        f"/api/v1/work-items/{work_id}",
        headers={"Authorization": worker["Authorization"]},
    )
    assert item.json()["status"] == "IN_PROGRESS"
    assert item.json()["exception_count"] >= 1
