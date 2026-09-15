import { apiFetch, ApiError } from "./apiClient";
import {
  CURSOR_KEY,
  LAST_SYNC_KEY,
  deleteWorkItem,
  deleteWorkTasksForItem,
  getMeta,
  listSendableCommands,
  listSendableEvidence,
  listWorkItems,
  listWorkTasks,
  nextClientSequence,
  putPendingCommand,
  putPendingEvidence,
  putWorkItem,
  putWorkTask,
  putWorkTasks,
  setMeta,
  type LocalWorkItem,
  type PendingCommand,
} from "./localStore";

export interface SyncCommandResult {
  command_id: string;
  status: string;
  reason_code?: string | null;
  message?: string | null;
  work_item_id?: string | null;
  work_item_status?: string | null;
  version?: number | null;
  idempotent_replay?: boolean;
  retryable?: boolean;
}

export interface SyncUploadResponse {
  results: SyncCommandResult[];
}

export interface SyncChange {
  sequence: number;
  entity_type: string;
  entity_id: string;
  event_type: string;
  work_item_id: string | null;
  payload: Record<string, unknown>;
  server_event_time: string;
}

export interface SyncDownloadResponse {
  changes: SyncChange[];
  next_cursor: number;
  has_more: boolean;
}

export type EnqueueResult =
  | { ok: true; command: PendingCommand }
  | { ok: false; error: string };

export async function enqueueCommand(input: {
  commandType: string;
  aggregateId: string | null;
  payload: Record<string, unknown>;
}): Promise<EnqueueResult> {
  const clientSequence = await nextClientSequence();
  const command: PendingCommand = {
    commandId: crypto.randomUUID(),
    idempotencyKey: crypto.randomUUID(),
    commandType: input.commandType,
    aggregateId: input.aggregateId,
    payload: input.payload,
    clientSequence,
    clientCreatedAt: new Date().toISOString(),
    schemaVersion: 1,
    status: "QUEUED",
  };
  await putPendingCommand(command);
  return { ok: true, command };
}

function applyResultToLocal(
  work: LocalWorkItem | undefined,
  result: SyncCommandResult,
  command: PendingCommand,
): LocalWorkItem | null {
  if (result.status !== "accepted" || !result.work_item_id) {
    return null;
  }
  const base: LocalWorkItem = work ?? {
    id: result.work_item_id,
    workType: String(command.payload.work_type ?? command.commandType),
    title: String(command.payload.title ?? command.commandType),
    status: "UNKNOWN",
    version: result.version ?? 1,
    contextRef: null,
    updatedAt: new Date().toISOString(),
  };
  return {
    ...base,
    id: result.work_item_id,
    status: result.work_item_status ?? base.status,
    version: result.version ?? base.version,
    updatedAt: new Date().toISOString(),
    localPendingCreate: false,
  };
}

/** When CreateWorkItem is accepted, remap local placeholder id → server id (tasks included). */
async function remapLocalCreate(
  command: PendingCommand,
  serverWorkId: string,
): Promise<void> {
  const localId = command.payload.local_work_id;
  if (typeof localId !== "string" || localId === serverWorkId) return;
  const items = await listWorkItems();
  const local = items.find((w) => w.id === localId);
  if (!local) return;
  await putWorkItem({
    ...local,
    id: serverWorkId,
    localPendingCreate: false,
    updatedAt: new Date().toISOString(),
  });
  await deleteWorkItem(localId);
  const tasks = await listWorkTasks(localId);
  await deleteWorkTasksForItem(localId);
  await putWorkTasks(
    tasks.map((t) => ({
      ...t,
      workItemId: serverWorkId,
    })),
  );
}

export interface UploadSummary {
  accepted: number;
  conflict: number;
  rejected: number;
  requiresReview: number;
  retryable: number;
  evidenceUploaded: number;
  evidenceFailed: number;
  networkError: boolean;
}

export async function uploadPendingCommands(limit = 20): Promise<UploadSummary> {
  const sendable = (await listSendableCommands()).slice(0, limit);
  const summary: UploadSummary = {
    accepted: 0,
    conflict: 0,
    rejected: 0,
    requiresReview: 0,
    retryable: 0,
    evidenceUploaded: 0,
    evidenceFailed: 0,
    networkError: false,
  };
  if (sendable.length === 0) {
    return summary;
  }

  for (const cmd of sendable) {
    await putPendingCommand({ ...cmd, status: "IN_FLIGHT" });
  }

  try {
    const body = {
      commands: sendable.map((c) => ({
        command_id: c.commandId,
        idempotency_key: c.idempotencyKey,
        command_type: c.commandType,
        aggregate_id: c.aggregateId,
        schema_version: c.schemaVersion,
        client_sequence: c.clientSequence,
        client_created_at: c.clientCreatedAt,
        payload: c.payload,
      })),
    };
    const response = await apiFetch<SyncUploadResponse>("/api/v1/sync/commands", {
      method: "POST",
      body: JSON.stringify(body),
    });

    const byId = new Map(response.results.map((r) => [r.command_id, r]));
    const workCache = new Map<string, LocalWorkItem>();
    for (const item of await listWorkItems()) {
      workCache.set(item.id, item);
    }

    for (const cmd of sendable) {
      const result = byId.get(cmd.commandId);
      if (!result) {
        await putPendingCommand({
          ...cmd,
          status: "RETRYABLE_FAILURE",
          lastError: "Missing result for command in batch response",
        });
        summary.retryable += 1;
        continue;
      }

      if (result.status === "accepted") {
        await putPendingCommand({
          ...cmd,
          status: "ACCEPTED",
          resultVersion: result.version ?? undefined,
          reasonCode: result.reason_code ?? undefined,
        });
        summary.accepted += 1;
        if (cmd.commandType === "CreateWorkItem" && result.work_item_id) {
          await remapLocalCreate(cmd, result.work_item_id);
        }
        const next = applyResultToLocal(
          cmd.aggregateId ? workCache.get(cmd.aggregateId) : undefined,
          result,
          cmd,
        );
        if (next) {
          await putWorkItem(next);
          workCache.set(next.id, next);
        }
      } else if (result.status === "requires_review") {
        await putPendingCommand({
          ...cmd,
          status: "REQUIRES_REVIEW",
          reasonCode: result.reason_code ?? undefined,
          lastError: result.message ?? undefined,
        });
        summary.requiresReview += 1;
      } else if (result.status === "conflict") {
        await putPendingCommand({
          ...cmd,
          status: "CONFLICT",
          reasonCode: result.reason_code ?? undefined,
          lastError: result.message ?? undefined,
        });
        summary.conflict += 1;
      } else if (result.status === "retryable") {
        await putPendingCommand({
          ...cmd,
          status: "RETRYABLE_FAILURE",
          reasonCode: result.reason_code ?? undefined,
          lastError: result.message ?? undefined,
        });
        summary.retryable += 1;
      } else {
        await putPendingCommand({
          ...cmd,
          status: "REJECTED",
          reasonCode: result.reason_code ?? undefined,
          lastError: result.message ?? undefined,
        });
        summary.rejected += 1;
      }
    }

    if (summary.accepted > 0) {
      await setMeta(LAST_SYNC_KEY, new Date().toISOString());
    }
    return summary;
  } catch (err) {
    summary.networkError = true;
    for (const cmd of sendable) {
      await putPendingCommand({
        ...cmd,
        status: "RETRYABLE_FAILURE",
        lastError: err instanceof ApiError ? err.message : "Network error during sync",
      });
    }
    return summary;
  }
}

export async function downloadChanges(): Promise<{ applied: number; hasMore: boolean }> {
  const cursorRaw = await getMeta(CURSOR_KEY);
  const cursor = cursorRaw ? Number(cursorRaw) : 0;
  let applied = 0;
  let hasMore = true;
  let current = Number.isFinite(cursor) ? cursor : 0;

  while (hasMore) {
    const page = await apiFetch<SyncDownloadResponse>(
      `/api/v1/sync/changes?cursor=${current}&limit=100`,
    );
    for (const change of page.changes) {
      if (change.entity_type === "work_item" && change.work_item_id) {
        const payload = change.payload;
        const existingList = await listWorkItems();
        const existing = existingList.find((w) => w.id === change.work_item_id);
        await putWorkItem({
          id: change.work_item_id,
          workType: String(payload.work_type ?? existing?.workType ?? "unknown"),
          title: String(payload.title ?? existing?.title ?? change.work_item_id),
          status: String(payload.status ?? existing?.status ?? "UNKNOWN"),
          version: Number(payload.version ?? existing?.version ?? 1),
          contextRef: existing?.contextRef ?? null,
          updatedAt: change.server_event_time,
        });
        applied += 1;
      } else if (change.entity_type === "work_task" && change.work_item_id) {
        const payload = change.payload;
        const taskId = String(payload.task_id ?? change.entity_id);
        const localTasks = await listWorkTasks(change.work_item_id);
        const existingTask = localTasks.find((t) => t.id === taskId || t.key === payload.title);
        const status = String(payload.status ?? "PENDING");
        await putWorkTask({
          id: taskId,
          workItemId: change.work_item_id,
          sequence: Number(payload.sequence ?? existingTask?.sequence ?? 0),
          key: existingTask?.key ?? taskId,
          title: String(payload.title ?? existingTask?.title ?? taskId),
          description: existingTask?.description ?? "",
          required: existingTask?.required ?? true,
          requiredEvidenceTypes: existingTask?.requiredEvidenceTypes ?? [],
          fields: existingTask?.fields ?? [],
          fieldValues: existingTask?.fieldValues ?? {},
          status:
            status === "COMPLETED" || status === "SKIPPED" ? status : "PENDING",
          notes: existingTask?.notes ?? "",
          updatedAt: change.server_event_time,
        });
        applied += 1;
      }
    }
    // Persist cursor only after durable local writes (invariant).
    current = page.next_cursor;
    await setMeta(CURSOR_KEY, String(current));
    hasMore = page.has_more;
  }

  if (applied > 0 || true) {
    await setMeta(LAST_SYNC_KEY, new Date().toISOString());
  }
  return { applied, hasMore: false };
}

export async function uploadPendingEvidence(): Promise<{
  uploaded: number;
  failed: number;
  networkError: boolean;
}> {
  const sendable = await listSendableEvidence();
  let uploaded = 0;
  let failed = 0;
  let networkError = false;
  if (sendable.length === 0) {
    return { uploaded, failed, networkError };
  }

  const { registerEvidence, uploadEvidenceContent } = await import("./evidenceClient");

  for (const item of sendable) {
    await putPendingEvidence({ ...item, status: "UPLOADING" });
    try {
      const registered = await registerEvidence({
        workItemId: item.workItemId,
        evidenceType: item.evidenceType,
        workTaskId: item.workTaskId,
        metadata: item.fileName ? { file_name: item.fileName } : {},
        capturedAtClient: item.capturedAtClient,
      });
      const done = await uploadEvidenceContent(registered.id, item.blob);
      await putPendingEvidence({
        ...item,
        status: "UPLOADED",
        serverEvidenceId: done.id,
      });
      uploaded += 1;
    } catch (err) {
      networkError = err instanceof TypeError;
      await putPendingEvidence({
        ...item,
        status: "FAILED",
        lastError: err instanceof Error ? err.message : "Evidence upload failed",
      });
      failed += 1;
    }
  }
  return { uploaded, failed, networkError };
}

export async function runFullSync(): Promise<UploadSummary> {
  const upload = await uploadPendingCommands();
  const evidence = await uploadPendingEvidence();
  await downloadChanges();
  return {
    ...upload,
    evidenceUploaded: evidence.uploaded,
    evidenceFailed: evidence.failed,
    networkError: upload.networkError || evidence.networkError,
  };
}
