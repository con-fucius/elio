/**
 * Durable local store for pending commands and local work projections.
 * Material UI state advances only after IndexedDB commit (INV-006).
 */

export type PendingCommandStatus =
  | "QUEUED"
  | "IN_FLIGHT"
  | "ACCEPTED"
  | "REQUIRES_REVIEW"
  | "CONFLICT"
  | "REJECTED"
  | "RETRYABLE_FAILURE";

export interface PendingCommand {
  commandId: string;
  idempotencyKey: string;
  commandType: string;
  aggregateId: string | null;
  payload: Record<string, unknown>;
  clientSequence: number;
  clientCreatedAt: string;
  schemaVersion: number;
  status: PendingCommandStatus;
  lastError?: string;
  reasonCode?: string;
  resultVersion?: number;
}

export interface LocalWorkItem {
  id: string;
  workType: string;
  title: string;
  status: string;
  version: number;
  contextRef: string | null;
  updatedAt: string;
  /** Pending create until server assigns real id — local placeholder key */
  localPendingCreate?: boolean;
}

export interface LocalWorkTask {
  id: string;
  workItemId: string;
  sequence: number;
  key: string;
  title: string;
  description: string;
  required: boolean;
  requiredEvidenceTypes: string[];
  fields: Array<{
    key: string;
    label: string;
    type?: string;
    required?: boolean;
    options?: string[];
  }>;
  fieldValues: Record<string, string>;
  status: "PENDING" | "COMPLETED" | "SKIPPED";
  notes: string;
  updatedAt: string;
}

export type PendingEvidenceStatus = "QUEUED" | "UPLOADING" | "UPLOADED" | "FAILED";

export interface PendingEvidence {
  localId: string;
  workItemId: string;
  workTaskId?: string;
  evidenceType: string;
  fileName: string | null;
  contentType: string;
  capturedAtClient: string;
  /** Binary kept as Blob for upload. */
  blob: Blob;
  status: PendingEvidenceStatus;
  lastError?: string;
  serverEvidenceId?: string;
}

export const NON_TERMINAL_STATUSES: ReadonlySet<PendingCommandStatus> = new Set([
  "QUEUED",
  "IN_FLIGHT",
  "CONFLICT",
  "REJECTED",
  "REQUIRES_REVIEW",
  "RETRYABLE_FAILURE",
]);

const DB_NAME = "elio";
const DB_VERSION = 3;
const STORE_PENDING = "pending_commands";
const STORE_WORK = "work_items";
const STORE_META = "meta";
const STORE_EVIDENCE = "pending_evidence";
const STORE_TASKS = "work_tasks";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_PENDING)) {
        const store = db.createObjectStore(STORE_PENDING, { keyPath: "commandId" });
        store.createIndex("by_idempotency_key", "idempotencyKey", { unique: true });
        store.createIndex("by_status", "status", { unique: false });
        store.createIndex("by_sequence", "clientSequence", { unique: false });
      }
      if (!db.objectStoreNames.contains(STORE_WORK)) {
        db.createObjectStore(STORE_WORK, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: "key" });
      }
      if (!db.objectStoreNames.contains(STORE_EVIDENCE)) {
        db.createObjectStore(STORE_EVIDENCE, { keyPath: "localId" });
      }
      if (!db.objectStoreNames.contains(STORE_TASKS)) {
        const tasks = db.createObjectStore(STORE_TASKS, { keyPath: "id" });
        tasks.createIndex("by_work_item", "workItemId", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB open failed"));
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("IndexedDB transaction failed"));
    tx.onabort = () => reject(tx.error ?? new Error("IndexedDB transaction aborted"));
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  stores: string[],
  fn: (tx: IDBTransaction) => Promise<T> | T,
): Promise<T> {
  const db = await openDb();
  try {
    const tx = db.transaction(stores, mode);
    const result = await fn(tx);
    await txDone(tx);
    return result;
  } finally {
    db.close();
  }
}

export async function putPendingCommand(command: PendingCommand): Promise<void> {
  await withStore("readwrite", [STORE_PENDING], (tx) => {
    tx.objectStore(STORE_PENDING).put(command);
  });
}

export async function getPendingCommand(commandId: string): Promise<PendingCommand | undefined> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_PENDING, "readonly");
      const req = tx.objectStore(STORE_PENDING).get(commandId);
      req.onsuccess = () => resolve(req.result as PendingCommand | undefined);
      req.onerror = () => reject(req.error ?? new Error("IndexedDB get failed"));
    });
  } finally {
    db.close();
  }
}

export async function listPendingCommands(): Promise<PendingCommand[]> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_PENDING, "readonly");
      const req = tx.objectStore(STORE_PENDING).getAll();
      req.onsuccess = () => resolve((req.result as PendingCommand[]) ?? []);
      req.onerror = () => reject(req.error ?? new Error("IndexedDB getAll failed"));
    });
  } finally {
    db.close();
  }
}

export async function countNonTerminalCommands(): Promise<number> {
  const all = await listPendingCommands();
  return all.filter((c) => NON_TERMINAL_STATUSES.has(c.status)).length;
}

export async function listSendableCommands(): Promise<PendingCommand[]> {
  const all = await listPendingCommands();
  return all
    .filter((c) => c.status === "QUEUED" || c.status === "RETRYABLE_FAILURE")
    .sort((a, b) => a.clientSequence - b.clientSequence);
}

export async function nextClientSequence(): Promise<number> {
  const all = await listPendingCommands();
  return all.reduce((max, c) => Math.max(max, c.clientSequence), 0) + 1;
}

export async function putWorkItem(item: LocalWorkItem): Promise<void> {
  await withStore("readwrite", [STORE_WORK], (tx) => {
    tx.objectStore(STORE_WORK).put(item);
  });
}

export async function deleteWorkItem(id: string): Promise<void> {
  await withStore("readwrite", [STORE_WORK], (tx) => {
    tx.objectStore(STORE_WORK).delete(id);
  });
}

export async function listWorkItems(): Promise<LocalWorkItem[]> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_WORK, "readonly");
      const req = tx.objectStore(STORE_WORK).getAll();
      req.onsuccess = () => resolve((req.result as LocalWorkItem[]) ?? []);
      req.onerror = () => reject(req.error ?? new Error("IndexedDB getAll failed"));
    });
  } finally {
    db.close();
  }
}

export async function getMeta(key: string): Promise<string | null> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_META, "readonly");
      const req = tx.objectStore(STORE_META).get(key);
      req.onsuccess = () => {
        const row = req.result as { key: string; value: string } | undefined;
        resolve(row?.value ?? null);
      };
      req.onerror = () => reject(req.error ?? new Error("IndexedDB get failed"));
    });
  } finally {
    db.close();
  }
}

export async function setMeta(key: string, value: string): Promise<void> {
  await withStore("readwrite", [STORE_META], (tx) => {
    tx.objectStore(STORE_META).put({ key, value });
  });
}

export const CURSOR_KEY = "sync_cursor";
export const LAST_SYNC_KEY = "last_successful_sync_at";

export async function putPendingEvidence(item: PendingEvidence): Promise<void> {
  await withStore("readwrite", [STORE_EVIDENCE], (tx) => {
    tx.objectStore(STORE_EVIDENCE).put(item);
  });
}

export async function listPendingEvidence(): Promise<PendingEvidence[]> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_EVIDENCE, "readonly");
      const req = tx.objectStore(STORE_EVIDENCE).getAll();
      req.onsuccess = () => resolve((req.result as PendingEvidence[]) ?? []);
      req.onerror = () => reject(req.error ?? new Error("IndexedDB getAll failed"));
    });
  } finally {
    db.close();
  }
}

export async function listSendableEvidence(): Promise<PendingEvidence[]> {
  const all = await listPendingEvidence();
  return all.filter((e) => e.status === "QUEUED" || e.status === "FAILED");
}

export async function countPendingEvidence(): Promise<number> {
  const all = await listPendingEvidence();
  return all.filter((e) => e.status === "QUEUED" || e.status === "UPLOADING" || e.status === "FAILED")
    .length;
}

export async function enqueuePendingEvidence(input: {
  workItemId: string;
  workTaskId?: string;
  evidenceType: string;
  file: Blob;
  fileName?: string;
}): Promise<PendingEvidence> {
  const item: PendingEvidence = {
    localId: crypto.randomUUID(),
    workItemId: input.workItemId,
    workTaskId: input.workTaskId,
    evidenceType: input.evidenceType,
    fileName: input.fileName ?? null,
    contentType: input.file.type || "application/octet-stream",
    capturedAtClient: new Date().toISOString(),
    blob: input.file,
    status: "QUEUED",
  };
  await putPendingEvidence(item);
  return item;
}

export async function putWorkTask(task: LocalWorkTask): Promise<void> {
  await withStore("readwrite", [STORE_TASKS], (tx) => {
    tx.objectStore(STORE_TASKS).put(task);
  });
}

export async function putWorkTasks(tasks: LocalWorkTask[]): Promise<void> {
  await withStore("readwrite", [STORE_TASKS], (tx) => {
    const store = tx.objectStore(STORE_TASKS);
    for (const t of tasks) store.put(t);
  });
}

export async function listWorkTasks(workItemId: string): Promise<LocalWorkTask[]> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_TASKS, "readonly");
      const index = tx.objectStore(STORE_TASKS).index("by_work_item");
      const req = index.getAll(workItemId);
      req.onsuccess = () => {
        const rows = (req.result as LocalWorkTask[]) ?? [];
        rows.sort((a, b) => a.sequence - b.sequence);
        resolve(rows);
      };
      req.onerror = () => reject(req.error ?? new Error("IndexedDB getAll failed"));
    });
  } finally {
    db.close();
  }
}

export async function getAllWorkTasks(): Promise<LocalWorkTask[]> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_TASKS, "readonly");
      const req = tx.objectStore(STORE_TASKS).getAll();
      req.onsuccess = () => resolve((req.result as LocalWorkTask[]) ?? []);
      req.onerror = () => reject(req.error ?? new Error("IndexedDB getAll failed"));
    });
  } finally {
    db.close();
  }
}

export async function deleteWorkTasksForItem(workItemId: string): Promise<void> {
  const tasks = await listWorkTasks(workItemId);
  await withStore("readwrite", [STORE_TASKS], (tx) => {
    const store = tx.objectStore(STORE_TASKS);
    for (const t of tasks) store.delete(t.id);
  });
}

/** Seed local checklist from a template when CreateWorkItem is queued (offline-ready). */
export async function seedLocalTasksFromTemplate(
  workItemId: string,
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
  }>,
): Promise<LocalWorkTask[]> {
  await deleteWorkTasksForItem(workItemId);
  const now = new Date().toISOString();
  const rows: LocalWorkTask[] = templateTasks.map((t, i) => ({
    id: crypto.randomUUID(),
    workItemId,
    sequence: i + 1,
    key: t.key,
    title: t.title,
    description: t.description ?? "",
    required: t.required ?? true,
    requiredEvidenceTypes: t.required_evidence_types ?? [],
    fields: t.fields ?? [],
    fieldValues: {},
    status: "PENDING",
    notes: "",
    updatedAt: now,
  }));
  await putWorkTasks(rows);
  return rows;
}
