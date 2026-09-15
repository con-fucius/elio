"""Anti-abuse: exception loophole, photo reuse, too-fast submit, min evidence size."""

import pytest
from conftest import TenantFixture
from httpx import AsyncClient
from test_journeys import _cmd, _login

from elio_api.config import get_settings


@pytest.fixture(autouse=True)
def _fast_tests(monkeypatch):
    monkeypatch.setattr(get_settings(), "min_execution_seconds", 0)
    monkeypatch.setattr(get_settings(), "min_evidence_bytes", 1)


@pytest.fixture
def _strict_photos(monkeypatch):
    monkeypatch.setattr(get_settings(), "min_evidence_bytes", 64)
    monkeypatch.setattr(get_settings(), "min_execution_seconds", 0)


async def _in_progress(
    client: AsyncClient, work_type: str = "facility_inspection"
) -> tuple[dict, dict, str]:
    sup = await _login(client, "supervisor@alpha-hospital.test", "SupervisorDev123!")
    worker = await _login(client, "worker@alpha-hospital.test", "WorkerDev123!")
    create = await client.post(
        "/api/v1/work-items",
        headers={"Authorization": sup["Authorization"]},
        json={
            "work_type": work_type,
            "title": "Anti-abuse target",
            "idempotency_key": __import__("uuid").uuid4().hex,
        },
    )
    work_id = create.json()["work_item_id"]
    await _cmd(client, sup, work_id, "/release")
    await _cmd(client, sup, work_id, "/assign", assignee_actor_id=worker["actor_id"])
    await _cmd(client, worker, work_id, "/accept")
    await _cmd(client, worker, work_id, "/start")
    return sup, worker, work_id


async def test_exception_outcome_without_raise_blocked(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    """Worker cannot jump to UNABLE_TO_ACCESS submit without RaiseException."""
    sup, worker, work_id = await _in_progress(client)
    res = await _cmd(
        client,
        worker,
        work_id,
        "/submit",
        reason="no access",
        outcome_type="UNABLE_TO_ACCESS",
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXCEPTION_REQUIRED"


async def test_exception_then_exception_outcome_allowed(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    sup, worker, work_id = await _in_progress(client)
    exc = await _cmd(
        client,
        worker,
        work_id,
        "/exception",
        reason="no_access| Gate locked, no guard on site",
    )
    assert exc.status_code == 200, exc.text
    assert exc.json()["status"] == "BLOCKED"
    submit = await _cmd(
        client,
        worker,
        work_id,
        "/submit",
        reason="no access",
        outcome_type="UNABLE_TO_ACCESS",
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "SUBMITTED"


async def test_photo_reuse_across_work_items_rejected(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    sup, worker, work_id = await _in_progress(client)
    # complete visual_check with photo on work A
    tasks = (
        await client.get(
            f"/api/v1/work-items/{work_id}/tasks",
            headers={"Authorization": worker["Authorization"]},
        )
    ).json()
    visual = next(t for t in tasks if t["key"] == "visual_check")
    reg = await client.post(
        f"/api/v1/work-items/{work_id}/evidence",
        headers={"Authorization": worker["Authorization"]},
        json={
            "work_item_id": work_id,
            "evidence_type": "photo",
            "work_task_id": visual["id"],
        },
    )
    assert reg.status_code == 201
    payload = b"x" * 200
    put = await client.put(
        f"/api/v1/evidence/{reg.json()['id']}/content",
        headers={
            "Authorization": worker["Authorization"],
            "Content-Type": "image/jpeg",
        },
        content=payload,
    )
    assert put.status_code == 200

    # second work item, same photo bytes
    sup2, worker2, work_b = await _in_progress(client)
    tasks_b = (
        await client.get(
            f"/api/v1/work-items/{work_b}/tasks",
            headers={"Authorization": worker2["Authorization"]},
        )
    ).json()
    visual_b = next(t for t in tasks_b if t["key"] == "visual_check")
    reg_b = await client.post(
        f"/api/v1/work-items/{work_b}/evidence",
        headers={"Authorization": worker2["Authorization"]},
        json={
            "work_item_id": work_b,
            "evidence_type": "photo",
            "work_task_id": visual_b["id"],
        },
    )
    assert reg_b.status_code == 201
    put_b = await client.put(
        f"/api/v1/evidence/{reg_b.json()['id']}/content",
        headers={
            "Authorization": worker2["Authorization"],
            "Content-Type": "image/jpeg",
        },
        content=payload,
    )
    assert put_b.status_code == 422
    assert put_b.json()["detail"]["code"] == "EVIDENCE_REUSED"


async def test_tiny_photo_rejected(
    client: AsyncClient, tenants: TenantFixture, _strict_photos
) -> None:
    sup, worker, work_id = await _in_progress(client)
    tasks = (
        await client.get(
            f"/api/v1/work-items/{work_id}/tasks",
            headers={"Authorization": worker["Authorization"]},
        )
    ).json()
    visual = next(t for t in tasks if t["key"] == "visual_check")
    reg = await client.post(
        f"/api/v1/work-items/{work_id}/evidence",
        headers={"Authorization": worker["Authorization"]},
        json={
            "work_item_id": work_id,
            "evidence_type": "photo",
            "work_task_id": visual["id"],
        },
    )
    put = await client.put(
        f"/api/v1/evidence/{reg.json()['id']}/content",
        headers={
            "Authorization": worker["Authorization"],
            "Content-Type": "image/jpeg",
        },
        content=b"tiny",
    )
    assert put.status_code == 422
    assert put.json()["detail"]["code"] == "EVIDENCE_TOO_SMALL"


async def test_too_fast_complete_rejected(
    client: AsyncClient, tenants: TenantFixture, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "min_execution_seconds", 3600)
    sup, worker, work_id = await _in_progress(client)
    # force started_at to now already from START — elapsed ~0 < 3600
    tasks = (
        await client.get(
            f"/api/v1/work-items/{work_id}/tasks",
            headers={"Authorization": worker["Authorization"]},
        )
    ).json()
    for t in tasks:
        if not t["required"]:
            continue
        field_values = {}
        for f in t.get("fields") or []:
            field_values[f["key"]] = (
                (f.get("options") or ["x"])[0] if f.get("type") == "choice" else "x"
            )
        if "photo" in t.get("required_evidence_types", []):
            reg = await client.post(
                f"/api/v1/work-items/{work_id}/evidence",
                headers={"Authorization": worker["Authorization"]},
                json={
                    "work_item_id": work_id,
                    "evidence_type": "photo",
                    "work_task_id": t["id"],
                },
            )
            await client.put(
                f"/api/v1/evidence/{reg.json()['id']}/content",
                headers={
                    "Authorization": worker["Authorization"],
                    "Content-Type": "image/jpeg",
                },
                content=b"y" * 200,
            )
        done = await _cmd(
            client,
            worker,
            work_id,
            f"/tasks/{t['id']}/complete",
            field_values=field_values,
        )
        assert done.status_code == 200, done.text
    submit = await _cmd(client, worker, work_id, "/submit")
    assert submit.status_code == 409
    assert submit.json()["detail"]["code"] == "EXECUTION_TOO_FAST"
