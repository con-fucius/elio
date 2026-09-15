"""WorkItem domain: hospital-profile state machine as executable code."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkItemStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL_STATUSES = frozenset(
    {WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED, WorkItemStatus.EXPIRED}
)


class WorkCommandType(StrEnum):
    RELEASE = "ReleaseWork"
    ASSIGN = "AssignWork"
    REASSIGN = "ReassignWork"
    ACCEPT = "AcceptAssignment"
    START = "StartWork"
    RAISE_EXCEPTION = "RaiseException"
    RESOLVE_EXCEPTION = "ResolveException"
    SUBMIT = "SubmitWork"
    WITHDRAW = "WithdrawSubmission"
    BEGIN_REVIEW = "BeginReview"
    ACCEPT_REVIEW = "AcceptReview"
    REJECT_REVIEW = "RejectSubmission"
    RETURN_TO_WORKER = "ReturnToWorker"
    RESUME = "ResumeWork"
    CANCEL = "CancelWork"
    COMPLETE_DIRECT = "CompleteWork"  # review-free only when policy allows


class IllegalTransition(Exception):
    def __init__(self, current: WorkItemStatus, command: WorkCommandType) -> None:
        self.current = current
        self.command = command
        super().__init__(f"Illegal transition: {command.value} from {current.value}")


# Explicit transition table — mirrors docs/state_machines/work_item_hospital.md
_TRANSITIONS: dict[tuple[WorkItemStatus, WorkCommandType], WorkItemStatus] = {
    (WorkItemStatus.DRAFT, WorkCommandType.RELEASE): WorkItemStatus.READY,
    (WorkItemStatus.DRAFT, WorkCommandType.CANCEL): WorkItemStatus.CANCELLED,
    (WorkItemStatus.READY, WorkCommandType.ASSIGN): WorkItemStatus.ASSIGNED,
    (WorkItemStatus.READY, WorkCommandType.CANCEL): WorkItemStatus.CANCELLED,
    (WorkItemStatus.ASSIGNED, WorkCommandType.ACCEPT): WorkItemStatus.ACCEPTED,
    (WorkItemStatus.ASSIGNED, WorkCommandType.REASSIGN): WorkItemStatus.ASSIGNED,
    (WorkItemStatus.ASSIGNED, WorkCommandType.CANCEL): WorkItemStatus.CANCELLED,
    (WorkItemStatus.ACCEPTED, WorkCommandType.START): WorkItemStatus.IN_PROGRESS,
    (WorkItemStatus.ACCEPTED, WorkCommandType.CANCEL): WorkItemStatus.CANCELLED,
    (WorkItemStatus.IN_PROGRESS, WorkCommandType.RAISE_EXCEPTION): WorkItemStatus.BLOCKED,
    (WorkItemStatus.IN_PROGRESS, WorkCommandType.SUBMIT): WorkItemStatus.SUBMITTED,
    (WorkItemStatus.IN_PROGRESS, WorkCommandType.CANCEL): WorkItemStatus.CANCELLED,
    (WorkItemStatus.BLOCKED, WorkCommandType.RESOLVE_EXCEPTION): WorkItemStatus.IN_PROGRESS,
    (WorkItemStatus.BLOCKED, WorkCommandType.SUBMIT): WorkItemStatus.SUBMITTED,
    (WorkItemStatus.BLOCKED, WorkCommandType.REASSIGN): WorkItemStatus.ASSIGNED,
    (WorkItemStatus.BLOCKED, WorkCommandType.CANCEL): WorkItemStatus.CANCELLED,
    (WorkItemStatus.SUBMITTED, WorkCommandType.BEGIN_REVIEW): WorkItemStatus.UNDER_REVIEW,
    (WorkItemStatus.SUBMITTED, WorkCommandType.REJECT_REVIEW): WorkItemStatus.REJECTED,
    (WorkItemStatus.SUBMITTED, WorkCommandType.WITHDRAW): WorkItemStatus.IN_PROGRESS,
    (WorkItemStatus.SUBMITTED, WorkCommandType.COMPLETE_DIRECT): WorkItemStatus.COMPLETED,
    (WorkItemStatus.UNDER_REVIEW, WorkCommandType.ACCEPT_REVIEW): WorkItemStatus.COMPLETED,
    (WorkItemStatus.UNDER_REVIEW, WorkCommandType.REJECT_REVIEW): WorkItemStatus.REJECTED,
    (WorkItemStatus.UNDER_REVIEW, WorkCommandType.RETURN_TO_WORKER): WorkItemStatus.IN_PROGRESS,
    (WorkItemStatus.REJECTED, WorkCommandType.RESUME): WorkItemStatus.IN_PROGRESS,
    (WorkItemStatus.REJECTED, WorkCommandType.SUBMIT): WorkItemStatus.SUBMITTED,
    (WorkItemStatus.REJECTED, WorkCommandType.REASSIGN): WorkItemStatus.ASSIGNED,
    (WorkItemStatus.REJECTED, WorkCommandType.CANCEL): WorkItemStatus.CANCELLED,
}

# Commands allowed while offline Class A/B without inventing new states.
OFFLINE_CLASS_A = frozenset(
    {
        WorkCommandType.RAISE_EXCEPTION,
        WorkCommandType.RESOLVE_EXCEPTION,
    }
)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    from_status: WorkItemStatus
    to_status: WorkItemStatus
    command: WorkCommandType


def next_status(current: WorkItemStatus, command: WorkCommandType) -> WorkItemStatus:
    key = (current, command)
    if key not in _TRANSITIONS:
        raise IllegalTransition(current, command)
    return _TRANSITIONS[key]


def apply_transition(current: WorkItemStatus, command: WorkCommandType) -> TransitionResult:
    to_status = next_status(current, command)
    return TransitionResult(from_status=current, to_status=to_status, command=command)
