import pytest

from elio_api.work.state_machine import (
    IllegalTransition,
    WorkCommandType,
    WorkItemStatus,
    apply_transition,
    next_status,
)


def test_draft_release_ready() -> None:
    assert next_status(WorkItemStatus.DRAFT, WorkCommandType.RELEASE) == WorkItemStatus.READY


def test_terminal_has_no_outgoing() -> None:
    for status in (
        WorkItemStatus.COMPLETED,
        WorkItemStatus.CANCELLED,
        WorkItemStatus.EXPIRED,
    ):
        with pytest.raises(IllegalTransition):
            next_status(status, WorkCommandType.START)


def test_hospital_requires_review_path() -> None:
    assert next_status(WorkItemStatus.SUBMITTED, WorkCommandType.BEGIN_REVIEW) == (
        WorkItemStatus.UNDER_REVIEW
    )


def test_withdraw_only_from_submitted() -> None:
    result = apply_transition(WorkItemStatus.SUBMITTED, WorkCommandType.WITHDRAW)
    assert result.to_status == WorkItemStatus.IN_PROGRESS
    with pytest.raises(IllegalTransition):
        next_status(WorkItemStatus.UNDER_REVIEW, WorkCommandType.WITHDRAW)
