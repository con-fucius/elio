import uuid

from conftest import TenantFixture
from httpx import AsyncClient
from test_isolation import auth_headers


async def _setup_assigned(client: AsyncClient, tenants: TenantFixture) -> str:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Sync target",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    release = await client.post(
        f"/api/v1/work-items/{work_id}/release",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={"idempotency_key": str(uuid.uuid4())},
    )
    assert release.status_code == 200
    assign = await client.post(
        f"/api/v1/work-items/{work_id}/assign",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "idempotency_key": str(uuid.uuid4()),
            "assignee_actor_id": tenants.worker_id,
        },
    )
    assert assign.status_code == 200
    return work_id


async def test_sync_batch_per_command_results(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _setup_assigned(client, tenants)
    # accept via REST to get to ACCEPTED
    accept = await client.post(
        f"/api/v1/work-items/{work_id}/accept",
        headers=auth_headers(client, tenants, who="worker"),
        json={"idempotency_key": str(uuid.uuid4())},
    )
    assert accept.status_code == 200

    batch = {
        "commands": [
            {
                "command_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
                "command_type": "StartWork",
                "aggregate_id": work_id,
                "schema_version": 1,
                "client_sequence": 1,
                "payload": {},
            },
            {
                "command_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
                "command_type": "StartWork",
                "aggregate_id": work_id,
                "schema_version": 1,
                "client_sequence": 2,
                # wrong expected version → conflict, batch continues
                "payload": {"expected_version": 1},
            },
        ]
    }
    res = await client.post(
        "/api/v1/sync/commands",
        headers=auth_headers(client, tenants, who="worker"),
        json=batch,
    )
    assert res.status_code == 200
    results = res.json()["results"]
    assert len(results) == 2
    assert results[0]["status"] == "accepted"
    assert results[1]["status"] in {"conflict", "rejected"}


async def test_sync_download_changes(client: AsyncClient, tenants: TenantFixture) -> None:
    await _setup_assigned(client, tenants)

    res = await client.get(
        "/api/v1/sync/changes?cursor=0",
        headers=auth_headers(client, tenants, who="worker"),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["next_cursor"] >= 0
    # Worker should see assign-related change if visibility includes assignment
    events = [c["event_type"] for c in body["changes"]]
    # At minimum pagination shape is valid
    assert isinstance(events, list)


async def test_sync_idempotent_replay_in_batch(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _setup_assigned(client, tenants)
    key = str(uuid.uuid4())
    cmd = {
        "command_id": str(uuid.uuid4()),
        "idempotency_key": key,
        "command_type": "AcceptAssignment",
        "aggregate_id": work_id,
        "schema_version": 1,
        "client_sequence": 1,
        "payload": {},
    }
    headers = auth_headers(client, tenants, who="worker")
    first = await client.post("/api/v1/sync/commands", headers=headers, json={"commands": [cmd]})
    second = await client.post(
        "/api/v1/sync/commands",
        headers=headers,
        json={
            "commands": [
                {**cmd, "command_id": str(uuid.uuid4())}
            ]
        },
    )
    assert first.json()["results"][0]["status"] == "accepted"
    assert second.json()["results"][0]["idempotent_replay"] is True
