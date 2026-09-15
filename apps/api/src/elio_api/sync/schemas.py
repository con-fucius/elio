from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SyncCommandEnvelope(BaseModel):
    command_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    command_type: str = Field(min_length=1, max_length=64)
    aggregate_id: str | None = Field(default=None, max_length=36)
    schema_version: int = Field(default=1, ge=1)
    client_sequence: int = Field(ge=0)
    client_created_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncUploadBody(BaseModel):
    commands: list[SyncCommandEnvelope] = Field(min_length=1, max_length=50)


class SyncCommandResult(BaseModel):
    command_id: str
    status: str
    reason_code: str | None = None
    message: str | None = None
    work_item_id: str | None = None
    work_item_status: str | None = None
    version: int | None = None
    idempotent_replay: bool = False
    retryable: bool = False


class SyncUploadResponse(BaseModel):
    results: list[SyncCommandResult]


class SyncChange(BaseModel):
    sequence: int
    entity_type: str
    entity_id: str
    event_type: str
    work_item_id: str | None
    payload: dict[str, Any]
    server_event_time: str


class SyncDownloadResponse(BaseModel):
    changes: list[SyncChange]
    next_cursor: int
    has_more: bool
