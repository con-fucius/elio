from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard API error envelope. Never stack traces or DB errors."""

    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable summary safe for operators")
    correlation_id: str = Field(description="Request correlation identifier")
    retryable: bool = Field(
        description="Whether a client may safely retry the same idempotency key"
    )


class HealthStatus(BaseModel):
    status: str
    service: str
    version: str
    details: dict[str, object] = Field(default_factory=dict)
