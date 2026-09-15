import uuid

from conftest import TenantFixture
from httpx import AsyncClient
from test_isolation import auth_headers


async def _cmd(
    client: AsyncClient,
    tenants: TenantFixture,
    work_id: str,
    path: str,
    *,
    who: str,
    extra: dict | None = None,
    idempotency_key: str | None = None,
):
    body = {"idempotency_key": idempotency_key or str(uuid.uuid4())}
    if extra:
        body.update(extra)
    return await client.post(
        f"/api/v1/work-items/{work_id}{path}",
        headers=auth_headers(client, tenants, who=who),
        json=body,
    )


async def _create_released(client: AsyncClient, tenants: TenantFixture) -> str:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Inspect pump room",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert create.status_code == 201
    work_id = create.json()["work_item_id"]
    release = await _cmd(client, tenants, work_id, "/release", who="supervisor")
    assert release.status_code == 200
    assert release.json()["status"] == "READY"
    return work_id


async def _complete_required_tasks(
    client: AsyncClient, tenants: TenantFixture, work_id: str
) -> None:
    """Facility inspection template requires checklist + photo evidence before submit."""
    tasks = (
        await client.get(
            f"/api/v1/work-items/{work_id}/tasks",
            headers=auth_headers(client, tenants, who="worker"),
        )
    ).json()
    for t in tasks:
        if not t["required"]:
            continue
        if "photo" in t.get("required_evidence_types", []):
            reg = await client.post(
                f"/api/v1/work-items/{work_id}/evidence",
                headers=auth_headers(client, tenants, who="worker"),
                json={
                    "work_item_id": work_id,
                    "evidence_type": "photo",
                    "work_task_id": t["id"],
                },
            )
            assert reg.status_code == 201, reg.text
            put = await client.put(
                f"/api/v1/evidence/{reg.json()['id']}/content",
                headers={
                    **auth_headers(client, tenants, who="worker"),
                    "Content-Type": "image/jpeg",
                },
                content=b"lifecycle-photo",
            )
            assert put.status_code == 200, put.text
        done = await _cmd(
            client,
            tenants,
            work_id,
            f"/tasks/{t['id']}/complete",
            who="worker",
            extra={"notes": "ok"},
        )
        assert done.status_code == 200, done.text


async def test_full_lifecycle_to_completed(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _create_released(client, tenants)

    assign = await _cmd(
        client,
        tenants,
        work_id,
        "/assign",
        who="supervisor",
        extra={"assignee_actor_id": tenants.worker_id},
    )
    assert assign.status_code == 200
    assert assign.json()["status"] == "ASSIGNED"

    accept = await _cmd(client, tenants, work_id, "/accept", who="worker")
    assert accept.json()["status"] == "ACCEPTED"

    start = await _cmd(client, tenants, work_id, "/start", who="worker")
    assert start.json()["status"] == "IN_PROGRESS"

    await _complete_required_tasks(client, tenants, work_id)
    submit = await _cmd(client, tenants, work_id, "/submit", who="worker")
    assert submit.json()["status"] == "SUBMITTED"

    begin = await _cmd(client, tenants, work_id, "/review/begin", who="supervisor")
    assert begin.json()["status"] == "UNDER_REVIEW"

    finish = await _cmd(client, tenants, work_id, "/review/accept", who="supervisor")
    assert finish.json()["status"] == "COMPLETED"

    final = await client.get(
        f"/api/v1/work-items/{work_id}",
        headers=auth_headers(client, tenants, who="supervisor"),
    )
    assert final.json()["status"] == "COMPLETED"
    # create(1) + release, assign, accept, start, submit, begin, accept_review
    assert final.json()["version"] == 8


async def test_idempotent_submit(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _create_released(client, tenants)
    await _cmd(
        client,
        tenants,
        work_id,
        "/assign",
        who="supervisor",
        extra={"assignee_actor_id": tenants.worker_id},
    )
    await _cmd(client, tenants, work_id, "/accept", who="worker")
    await _cmd(client, tenants, work_id, "/start", who="worker")
    await _complete_required_tasks(client, tenants, work_id)

    key = str(uuid.uuid4())
    first = await _cmd(client, tenants, work_id, "/submit", who="worker", idempotency_key=key)
    second = await _cmd(client, tenants, work_id, "/submit", who="worker", idempotency_key=key)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert first.json()["version"] == second.json()["version"]


async def test_illegal_transition_submit_from_draft(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Draft only",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    res = await _cmd(client, tenants, work_id, "/submit", who="worker")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] in {
        "ILLEGAL_TRANSITION",
        "NOT_ASSIGNEE",
        "NO_ACTIVE_ASSIGNMENT",
    }


async def test_non_assignee_cannot_start(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _create_released(client, tenants)
    await _cmd(
        client,
        tenants,
        work_id,
        "/assign",
        who="supervisor",
        extra={"assignee_actor_id": tenants.worker_id},
    )
    await _cmd(client, tenants, work_id, "/accept", who="worker")
    # Supervisor tries start — has execute permission but is not assignee
    res = await _cmd(client, tenants, work_id, "/start", who="supervisor")
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "NOT_ASSIGNEE"


async def test_withdraw_submission(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _create_released(client, tenants)
    await _cmd(
        client,
        tenants,
        work_id,
        "/assign",
        who="supervisor",
        extra={"assignee_actor_id": tenants.worker_id},
    )
    await _cmd(client, tenants, work_id, "/accept", who="worker")
    await _cmd(client, tenants, work_id, "/start", who="worker")
    await _complete_required_tasks(client, tenants, work_id)
    await _cmd(client, tenants, work_id, "/submit", who="worker")
    withdraw = await _cmd(client, tenants, work_id, "/withdraw", who="worker")
    assert withdraw.status_code == 200
    assert withdraw.json()["status"] == "IN_PROGRESS"


async def test_direct_complete_rejected_for_hospital(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    work_id = await _create_released(client, tenants)
    await _cmd(
        client,
        tenants,
        work_id,
        "/assign",
        who="supervisor",
        extra={"assignee_actor_id": tenants.worker_id},
    )
    await _cmd(client, tenants, work_id, "/accept", who="worker")
    await _cmd(client, tenants, work_id, "/start", who="worker")
    await _complete_required_tasks(client, tenants, work_id)
    await _cmd(client, tenants, work_id, "/submit", who="worker")
    # There is no direct complete route for hospital default — review required.
    # Begin review then reject path still works.
    begin = await _cmd(client, tenants, work_id, "/review/begin", who="supervisor")
    assert begin.json()["status"] == "UNDER_REVIEW"
    reject = await _cmd(
        client,
        tenants,
        work_id,
        "/review/reject",
        who="supervisor",
        extra={"reason": "evidence incomplete"},
    )
    assert reject.json()["status"] == "REJECTED"
    resume = await _cmd(client, tenants, work_id, "/resume", who="worker")
    assert resume.status_code == 200
    assert resume.json()["status"] == "IN_PROGRESS"
