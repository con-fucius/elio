import { apiFetch } from "./apiClient";

export interface TemplateField {
  key: string;
  label: string;
  type?: string;
  required?: boolean;
  options?: string[];
}

export interface WorkTaskRead {
  id: string;
  work_item_id: string;
  sequence: number;
  key: string;
  title: string;
  description: string;
  required: boolean;
  required_evidence_types: string[];
  fields: TemplateField[];
  field_values: Record<string, string>;
  status: string;
  notes: string;
}

export interface TemplateRead {
  id: string;
  work_type: string;
  domain: string;
  title: string;
  description: string;
  outcome_types: string[];
  default_outcome_type: string;
  review_required: boolean;
  version: number;
  status: string;
  tasks: Array<{
    id: string;
    sequence: number;
    key: string;
    title: string;
    description: string;
    required: boolean;
    required_evidence_types: string[];
    fields?: TemplateField[];
  }>;
}

export async function listTemplates(): Promise<TemplateRead[]> {
  return apiFetch<TemplateRead[]>("/api/v1/templates");
}

export async function fetchWorkTasks(workItemId: string): Promise<WorkTaskRead[]> {
  return apiFetch<WorkTaskRead[]>(`/api/v1/work-items/${workItemId}/tasks`);
}
