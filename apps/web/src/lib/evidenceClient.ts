import { apiFetch } from "./apiClient";

export interface EvidenceListItem {
  id: string;
  work_item_id: string;
  work_task_id: string | null;
  evidence_type: string;
  verification_status: string;
  content_type: string;
  size_bytes: number | null;
  checksum: string | null;
  captured_at_client: string | null;
  received_at_server: string;
}

export interface EvidenceRead {
  id: string;
  work_item_id: string;
  evidence_type: string;
  verification_status: string;
  content_type: string;
  size_bytes: number | null;
  checksum: string | null;
  captured_at_client: string | null;
  received_at_server: string;
}

export async function registerEvidence(input: {
  workItemId: string;
  evidenceType: string;
  metadata?: Record<string, unknown>;
  capturedAtClient?: string;
  workTaskId?: string;
}): Promise<EvidenceRead> {
  return apiFetch<EvidenceRead>(`/api/v1/work-items/${input.workItemId}/evidence`, {
    method: "POST",
    body: JSON.stringify({
      work_item_id: input.workItemId,
      evidence_type: input.evidenceType,
      work_task_id: input.workTaskId ?? null,
      metadata: input.metadata ?? {},
      captured_at_client: input.capturedAtClient ?? new Date().toISOString(),
    }),
  });
}

export async function uploadEvidenceContent(
  evidenceId: string,
  data: Blob,
): Promise<EvidenceRead> {
  const buffer = await data.arrayBuffer();
  return apiFetch<EvidenceRead>(`/api/v1/evidence/${evidenceId}/content`, {
    method: "PUT",
    headers: { "Content-Type": data.type || "application/octet-stream" },
    body: buffer,
  });
}

export async function listEvidence(workItemId: string): Promise<EvidenceListItem[]> {
  return apiFetch<EvidenceListItem[]>(`/api/v1/work-items/${workItemId}/evidence`);
}

export async function downloadEvidence(
  evidenceId: string,
): Promise<{ blob: Blob; contentType: string; name: string }> {
  const token = (await import("./auth")).getAccessToken();
  const res = await fetch(`/api/v1/evidence/${evidenceId}/content`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Could not download evidence (${res.status})`);
  }
  const blob = await res.blob();
  const name = res.headers.get("X-Evidence-Checksum")
    ? `evidence-${evidenceId.slice(0, 8)}`
    : `evidence-${evidenceId.slice(0, 8)}`;
  return { blob, contentType: blob.type || "application/octet-stream", name };
}
