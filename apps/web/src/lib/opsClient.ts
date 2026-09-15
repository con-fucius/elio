import { uploadPendingCommands } from "./syncEngine";
import { WorkCommands } from "./workActions";
import { fetchServerWorkItems, type ServerWorkItem } from "./serverSync";

export type OpsView = "queue" | "assigned" | "review";

export interface OpsRow extends ServerWorkItem {
  pendingAttention: boolean;
}

export async function loadOpsWork(statusFilter: "active" | "all" = "active"): Promise<
  ServerWorkItem[]
> {
  void statusFilter;
  return fetchServerWorkItems("any");
}

/**
 * Ops decisions go through the durable command queue (same as field work).
 * When online, we flush the queue immediately so the UI can refresh from the server.
 * Offline: commands stay QUEUED until Send pending / next online sync.
 */
async function queueAndFlush(fn: () => Promise<unknown>): Promise<void> {
  await fn();
  if (typeof navigator !== "undefined" && navigator.onLine) {
    await uploadPendingCommands();
  }
}

export async function submitAssign(
  workId: string,
  assigneeActorId: string,
  reason = "",
): Promise<void> {
  await queueAndFlush(() => WorkCommands.assign(workId, assigneeActorId, reason));
}

export async function submitBeginReview(workId: string): Promise<void> {
  await queueAndFlush(() => WorkCommands.beginReview(workId));
}

export async function submitAcceptReview(
  workId: string,
  reason: string,
): Promise<void> {
  await queueAndFlush(() => WorkCommands.acceptReview(workId, reason));
}

export async function submitRejectReview(
  workId: string,
  reason: string,
): Promise<void> {
  await queueAndFlush(() => WorkCommands.rejectReview(workId, reason));
}

export async function submitCancel(
  workId: string,
  reason: string,
): Promise<void> {
  await queueAndFlush(() => WorkCommands.cancel(workId, reason));
}

export async function submitUnblock(
  workId: string,
  reason: string,
): Promise<void> {
  await queueAndFlush(() => WorkCommands.resolveException(workId));
  void reason;
}

export function rowActions(status: string): Array<{
  id: string;
  label: string;
  primary: boolean;
  needsReason: boolean;
}> {
  switch (status) {
    case "READY":
      return [{ id: "assign", label: "Assign", primary: true, needsReason: false }];
    case "ASSIGNED":
      return [{ id: "cancel", label: "Cancel", primary: false, needsReason: true }];
    case "BLOCKED":
      return [{ id: "unblock", label: "Unblock", primary: true, needsReason: false }];
    case "SUBMITTED":
      return [
        { id: "begin_review", label: "Begin review", primary: true, needsReason: false },
        { id: "cancel", label: "Cancel", primary: false, needsReason: true },
      ];
    case "UNDER_REVIEW":
      return [
        { id: "accept_review", label: "Accept", primary: true, needsReason: false },
        { id: "reject_review", label: "Reject", primary: false, needsReason: true },
      ];
    default:
      return [];
  }
}

export const STATUS_TEXT: Record<string, string> = {
  DRAFT: "Draft",
  READY: "Ready",
  ASSIGNED: "Assigned",
  ACCEPTED: "Accepted",
  IN_PROGRESS: "In progress",
  BLOCKED: "Blocked",
  SUBMITTED: "Submitted",
  UNDER_REVIEW: "In review",
  REJECTED: "Needs rework",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
  EXPIRED: "Expired",
};

export function statusText(s: string): string {
  return STATUS_TEXT[s] ?? s;
}
