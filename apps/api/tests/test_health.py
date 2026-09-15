from httpx import AsyncClient


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "elio-api"


async def test_readiness_checks_database(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["details"]["database"] == "ok"


async def test_correlation_id_header_present(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert "X-Correlation-ID" in response.headers


async def test_correlation_id_echoed_when_provided(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health/live",
        headers={"X-Correlation-ID": "test-corr-123"},
    )
    assert response.headers["X-Correlation-ID"] == "test-corr-123"
