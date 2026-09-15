import { apiFetch } from "./apiClient";

export interface ActorRead {
  id: string;
  display_name: string;
  email: string;
  status: string;
  roles: string[];
}

export async function listActors(): Promise<ActorRead[]> {
  return apiFetch<ActorRead[]>("/api/v1/actors");
}
