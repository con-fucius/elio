import { apiFetch } from "./apiClient";
import {
  putWorkItem,
  putWorkTasks,
  type LocalWorkTask,
  type LocalWorkItem,
} from "./localStore";

export interface ServerWorkItem {
  id: string;
  tenant_id: string;
  work_type: string;
  domain: string;
  status: string;
  priority: number;
  version: number;
  title: string;
  context_ref: string | null;
  active_assignment_id: string | null;
  template_id: string | null;
  template_version: number | null;
  outcome_type: string | null;
  exception_count: number;
  created_at: string;
}

export interface ServerWorkTask {
  id: string;
  work_item_id: string;
  sequence: number;
  key: string;
  title: string;
  description: string;
  required: boolean;
  required_evidence_types: string[];
  fields: Array<{
    key: string;
    label: string;
    type?: string;
    required?: boolean;
    options?: string[];
  }>;
  field_values: Record<string, string>;
  status: string;
  notes: string;
}

export async function fetchServerWorkItems(
  assignedTo: "me" | "any" = "any",
): Promise<ServerWorkItem[]> {
  const q = assignedTo === "me" ? "?status_filter=active&assigned_to=me" : "?status_filter=all";
  return apiFetch<ServerWorkItem[]>(`/api/v1/work-items${q}`);
}

export async function fetchServerTasks(workItemId: string): Promise<ServerWorkTask[]> {
  return apiFetch<ServerWorkTask[]>(`/api/v1/work-items/${workItemId}/tasks`);
}

/** Pull authoritative work + tasks from server into IndexedDB (refresh). */
export async function refreshFromServer(
  assignedTo: "me" | "any" = "any",
): Promise<{ work: number; tasks: number }> {
  const items = await fetchServerWorkItems(assignedTo);
  let taskCount = 0;
  for (const item of items) {
    const local: LocalWorkItem = {
      id: item.id,
      workType: item.work_type,
      title: item.title,
      status: item.status,
      version: item.version,
      contextRef: item.context_ref,
      updatedAt: item.created_at,
      localPendingCreate: false,
    };
    await putWorkItem(local);
    const tasks = await fetchServerTasks(item.id);
    taskCount += tasks.length;
    const mapped: LocalWorkTask[] = tasks.map((t) => ({
      id: t.id,
      workItemId: t.work_item_id,
      sequence: t.sequence,
      key: t.key,
      title: t.title,
      description: t.description,
      required: t.required,
      requiredEvidenceTypes: t.required_evidence_types,
      fields: t.fields ?? [],
      fieldValues: t.field_values ?? {},
      status:
        t.status === "COMPLETED" || t.status === "SKIPPED" || t.status === "PENDING"
          ? t.status
          : "PENDING",
      notes: t.notes,
      updatedAt: new Date().toISOString(),
    }));
    await putWorkTasks(mapped);
  }
  return { work: items.length, tasks: taskCount };
}
