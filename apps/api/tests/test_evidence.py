import hashlib
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


async def _in_progress(client: AsyncClient, tenants: TenantFixture) -> str:
    create = await client.post(
        "/api/v1/work-items",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={
            "work_type": "facility_inspection",
            "title": "Evidence work",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    work_id = create.json()["work_item_id"]
    for path, who, extra in [
        ("/release", "supervisor", {}),
        ("/assign", "supervisor", {"assignee_actor_id": tenants.worker_id}),
        ("/accept", "worker", {}),
        ("/start", "worker", {}),
    ]:
        body = {"idempotency_key": str(uuid.uuid4()), **extra}
        res = await client.post(
            f"/api/v1/work-items/{work_id}{path}",
            headers=auth_headers(client, tenants, who=who),
            json=body,
        )
        assert res.status_code == 200, res.text
    return work_id


async def test_evidence_register_upload_download(
    client: AsyncClient, tenants: TenantFixture
) -> None:
    work_id = await _in_progress(client, tenants)
    headers = auth_headers(client, tenants, who="worker")

    reg = await client.post(
        f"/api/v1/work-items/{work_id}/evidence",
        headers=headers,
        json={
            "work_item_id": work_id,
            "evidence_type": "photo",
            "metadata": {"caption": "pump gauge"},
        },
    )
    assert reg.status_code == 201, reg.text
    evidence_id = reg.json()["id"]
    assert reg.json()["verification_status"] == "CAPTURED"

    payload = b"fake-image-bytes-for-evidence"
    checksum = hashlib.sha256(payload).hexdigest()
    put = await client.put(
        f"/api/v1/evidence/{evidence_id}/content",
        headers={**headers, "Content-Type": "image/jpeg"},
        content=payload,
    )
    assert put.status_code == 200, put.text
    assert put.json()["verification_status"] == "UPLOADED"
    assert put.json()["checksum"] == checksum
    assert put.json()["size_bytes"] == len(payload)

    got = await client.get(f"/api/v1/evidence/{evidence_id}/content", headers=headers)
    assert got.status_code == 200
    assert got.content == payload
    assert got.headers["X-Evidence-Checksum"] == checksum


async def test_evidence_other_worker_denied(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _in_progress(client, tenants)
    reg = await client.post(
        f"/api/v1/work-items/{work_id}/evidence",
        headers=auth_headers(client, tenants, who="worker"),
        json={"work_item_id": work_id, "evidence_type": "photo"},
    )
    evidence_id = reg.json()["id"]

    # Beta worker is different tenant — should 404
    got = await client.get(
        f"/api/v1/evidence/{evidence_id}/content",
        headers=auth_headers(client, tenants, who="other_worker"),
    )
    assert got.status_code == 404


async def test_evidence_rejected_on_terminal(client: AsyncClient, tenants: TenantFixture) -> None:
    work_id = await _in_progress(client, tenants)
    # submit then cancel path: cancel from IN_PROGRESS
    cancel = await client.post(
        f"/api/v1/work-items/{work_id}/cancel",
        headers=auth_headers(client, tenants, who="supervisor"),
        json={"idempotency_key": str(uuid.uuid4()), "reason": "site closed"},
    )
    assert cancel.status_code == 200
    reg = await client.post(
        f"/api/v1/work-items/{work_id}/evidence",
        headers=auth_headers(client, tenants, who="worker"),
        json={"work_item_id": work_id, "evidence_type": "photo"},
    )
    assert reg.status_code == 409
