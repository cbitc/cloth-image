import type {
  ClothingImage,
  CreateTasksResponse,
  DesignImage,
  MaterialTagDef,
  MaterialTagInput,
  SearchClothingResponse,
  SiteOption,
  TaskDetail,
  TaskSummary,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string; provider_mode: string }>("/api/health"),

  listSites: () => request<{ mode: string; sites: SiteOption[] }>("/api/search/sites"),

  searchClothing: (payload: { sites: string[]; query: string; count: number }) =>
    request<SearchClothingResponse>("/api/search/clothing", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  taxonomy: () => request<MaterialTagDef[]>("/api/material-taxonomy"),

  createTasks: (payload: {
    clothing_image_ids: string[];
    design_idea?: string;
    auto_generate?: boolean;
    require_material_selection?: boolean;
  }) =>
    request<CreateTasksResponse>("/api/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listTasks: (status?: string) =>
    request<TaskSummary[]>(`/api/tasks${status ? `?status=${status}` : ""}`),

  getTask: (id: string) => request<TaskDetail>(`/api/tasks/${id}`),

  confirmMaterials: (id: string, tags: MaterialTagInput[]) =>
    request<TaskDetail>(`/api/tasks/${id}/confirm-materials`, {
      method: "POST",
      body: JSON.stringify({ tags }),
    }),

  selectMaterials: (id: string, materialImageIds: string[] | null) =>
    request<TaskDetail>(`/api/tasks/${id}/select-materials`, {
      method: "POST",
      body: JSON.stringify({ material_image_ids: materialImageIds }),
    }),

  generate: (id: string, designIdea: string, numCandidates: number) =>
    request<TaskDetail>(`/api/tasks/${id}/generate`, {
      method: "POST",
      body: JSON.stringify({ design_idea: designIdea, num_candidates: numCandidates }),
    }),

  retry: (id: string) =>
    request<TaskDetail>(`/api/tasks/${id}/retry`, { method: "POST" }),

  deleteTask: (id: string) => request<void>(`/api/tasks/${id}`, { method: "DELETE" }),
};

export const taskEventsUrl = (id: string) => `${API_BASE}/api/tasks/${id}/events`;
export const boardStreamUrl = () => `${API_BASE}/api/events/stream`;

export type { ClothingImage, DesignImage, TaskDetail, TaskSummary };
