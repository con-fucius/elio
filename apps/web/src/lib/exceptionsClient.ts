import { apiFetch } from "./apiClient";

export interface WorkExceptionRow {
  id: string;
  work_item_id: string;
  category: string;
  detail: string;
  status: string;
  raised_by: string;
  raised_at: string;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_notes: string;
}

export async function listWorkExceptions(
  workItemId: string,
  openOnly = false,
): Promise<WorkExceptionRow[]> {
  const q = openOnly ? "?open_only=true" : "";
  return apiFetch<WorkExceptionRow[]>(
    `/api/v1/work-items/${workItemId}/exceptions${q}`,
  );
}

export const EXCEPTION_CATEGORY_TEXT: Record<string, string> = {
  no_access: "Site unavailable / no access",
  unsafe: "Unsafe conditions",
  wrong_site: "Wrong site or wrong assignment",
  missing_asset: "Equipment or stock missing",
  other: "Other",
};

export function exceptionCategoryText(code: string): string {
  return EXCEPTION_CATEGORY_TEXT[code] ?? code;
}
