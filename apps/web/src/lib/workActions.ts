import {
  getAllWorkTasks,
  putWorkItem,
  putWorkTask,
  seedLocalTasksFromTemplate,
} from "./localStore";
import { enqueueCommand } from "./syncEngine";

export async function queueWorkCommand(
  commandType: string,
  workItemId: string,
  payload: Record<string, unknown> = {},
) {
  return enqueueCommand({
    commandType,
    aggregateId: workItemId,
    payload: { ...payload, work_item_id: workItemId },
  });
}

/** Offline-first create: local projection + template checklist, then queue CreateWorkItem. */
export async function createWorkFromTemplate(input: {
  workType: string;
  title: string;
  templateTasks: Array<{
    key: string;
    title: string;
    description?: string;
    required?: boolean;
    required_evidence_types?: string[];
    fields?: Array<{
      key: string;
      label: string;
      type?: string;
      required?: boolean;
      options?: string[];
    }>;
  }>;
  priority?: number;
}): Promise<{ localWorkId: string }> {
  const localWorkId = crypto.randomUUID();
  const now = new Date().toISOString();
  await putWorkItem({
    id: localWorkId,
    workType: input.workType,
    title: input.title,
    status: "DRAFT",
    version: 1,
    contextRef: null,
    updatedAt: now,
    localPendingCreate: true,
  });
  await seedLocalTasksFromTemplate(localWorkId, input.templateTasks);
  await enqueueCommand({
    commandType: "CreateWorkItem",
    aggregateId: null,
    payload: {
      work_type: input.workType,
      title: input.title,
      priority: input.priority ?? 100,
      local_work_id: localWorkId,
    },
  });
  return { localWorkId };
}

async function applyLocalTaskStatus(
  taskId: string,
  status: "COMPLETED" | "SKIPPED",
  notes: string,
): Promise<void> {
  const all = await getAllWorkTasks();
  const existing = all.find((t) => t.id === taskId);
  if (!existing) return;
  await putWorkTask({
    ...existing,
    status,
    notes: notes || existing.notes,
    updatedAt: new Date().toISOString(),
  });
}

export const WorkCommands = {
  release: (id: string) => queueWorkCommand("ReleaseWork", id),
  assign: (id: string, assigneeActorId: string, reason = "") =>
    queueWorkCommand("AssignWork", id, { assignee_actor_id: assigneeActorId, reason }),
  accept: (id: string) => queueWorkCommand("AcceptAssignment", id),
  start: (id: string) => queueWorkCommand("StartWork", id),
  submit: (id: string, reason = "", outcomeType?: string) =>
    queueWorkCommand("SubmitWork", id, {
      reason,
      ...(outcomeType ? { outcome_type: outcomeType } : {}),
    }),
  raiseException: (id: string, reason: string) =>
    queueWorkCommand("RaiseException", id, {
      reason,
      // structured when UI provides category code
      ...(reason.includes("|")
        ? { exception_category: reason.split("|")[0]?.trim(), exception_detail: reason.split("|").slice(1).join("|").trim() }
        : {}),
    }),
  resolveException: (id: string) => queueWorkCommand("ResolveException", id),
  withdraw: (id: string) => queueWorkCommand("WithdrawSubmission", id),
  beginReview: (id: string) => queueWorkCommand("BeginReview", id),
  acceptReview: (id: string, reason = "") =>
    queueWorkCommand("AcceptReview", id, { reason }),
  rejectReview: (id: string, reason: string) =>
    queueWorkCommand("RejectSubmission", id, { reason }),
  resume: (id: string) => queueWorkCommand("ResumeWork", id),
  cancel: (id: string, reason: string) =>
    queueWorkCommand("CancelWork", id, { reason }),
  async completeTask(
    workItemId: string,
    taskId: string,
    notes = "",
    fieldValues: Record<string, string> = {},
  ) {
    await queueWorkCommand("CompleteTask", workItemId, {
      task_id: taskId,
      notes,
      action: "CompleteTask",
      field_values: fieldValues,
    });
    await applyLocalTaskStatus(taskId, "COMPLETED", notes);
  },
  async skipTask(workItemId: string, taskId: string, notes = "") {
    await queueWorkCommand("SkipTask", workItemId, {
      task_id: taskId,
      notes,
      action: "SkipTask",
    });
    await applyLocalTaskStatus(taskId, "SKIPPED", notes);
  },
  async saveTaskDraft(
    workItemId: string,
    taskId: string,
    notes: string,
    fieldValues: Record<string, string>,
  ) {
    // Direct REST so draft saves don't go through command queue (editable before submit)
    const { apiFetch } = await import("./apiClient");
    const { getAllWorkTasks, putWorkTask } = await import("./localStore");
    await apiFetch(`/api/v1/work-items/${workItemId}/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ notes, field_values: fieldValues }),
    });
    const all = await getAllWorkTasks();
    const t = all.find((x) => x.id === taskId);
    if (t) {
      await putWorkTask({
        ...t,
        notes,
        fieldValues,
        updatedAt: new Date().toISOString(),
      });
    }
  },
  async editWorkTitle(workItemId: string, title: string) {
    const { apiFetch } = await import("./apiClient");
    await apiFetch(`/api/v1/work-items/${workItemId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    const { putWorkItem, listWorkItems } = await import("./localStore");
    const items = await listWorkItems();
    const w = items.find((x) => x.id === workItemId);
    if (w) {
      await putWorkItem({
        ...w,
        title,
        updatedAt: new Date().toISOString(),
      });
    }
  },
} as const;
