import type {
  AuthUser,
  CardOptions,
  ClothingImage,
  CreateTasksResponse,
  DesignImage,
  IdentifyCacheStats,
  MaterialCardPatch,
  MaterialTagDef,
  SearchClothingResponse,
  SettingsView,
  SiteOption,
  TaskDetail,
  TaskSummary,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

/** 后端错误：`code` 用于机器判断（如 SUBSCRIPTION_REQUIRED），`detail` 用于展示。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | undefined,
    readonly detail: string,
  ) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  let code: string | undefined;
  try {
    const body = await res.json();
    const raw = body?.detail ?? body?.error?.message ?? body;
    detail = typeof raw === "string" ? raw : JSON.stringify(raw);
    code = typeof body?.code === "string" ? body.code : body?.error?.type;
  } catch {
    /* ignore */
  }
  return new ApiError(res.status, code, detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    // 登录态在 httpOnly cookie 里，跨端口请求必须带凭据
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () =>
    request<{ status: string; abilities: Record<string, string> }>("/api/health"),

  // ---- 登录 / 许可（entitlement-api-new） ----
  requestLogin: (email: string) =>
    request<{ email: string; expires_at: string }>("/api/auth/request-login", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  verifyLogin: (email: string, code: string) =>
    request<AuthUser>("/api/auth/verify-login", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    }),

  /** 查询当前登录状态与有效许可（未登录时抛 401 ApiError） */
  me: () => request<AuthUser>("/api/auth/me"),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  listSites: () =>
    request<{ provider: string; sites: SiteOption[] }>("/api/search/sites"),

  searchClothing: (payload: { sites: string[]; query: string; count: number }) =>
    request<SearchClothingResponse>("/api/search/clothing", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  taxonomy: () => request<MaterialTagDef[]>("/api/material-taxonomy"),

  /** 材质卡片的受控取值（图案 / 光泽 / 品类 / 面料名…），避免前端硬编码漂移 */
  cardOptions: () =>
    request<CardOptions>("/api/material-taxonomy/card-options"),

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

  /** 编辑材质卡片（局部更新，只写库不推进状态） */
  updateMaterialCard: (id: string, patch: MaterialCardPatch) =>
    request<TaskDetail>(`/api/tasks/${id}/material-card`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  /** ★检查点1：确认材质卡片 → 触发面料图检索 */
  confirmMaterials: (id: string) =>
    request<TaskDetail>(`/api/tasks/${id}/confirm-materials`, { method: "POST" }),

  /** 编辑入口2「换小样」：上传面料图（进参考图池，参与生图） */
  uploadMaterialImages: async (id: string, files: FileList | File[]) => {
    const form = new FormData();
    for (const file of Array.from(files)) form.append("files", file);
    const res = await fetch(`${API_BASE}/api/tasks/${id}/material-images`, {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) throw await toApiError(res);
    return (await res.json()) as TaskDetail;
  },

  deleteMaterialImage: (id: string, imageId: string) =>
    request<TaskDetail>(`/api/tasks/${id}/material-images/${imageId}`, {
      method: "DELETE",
    }),

  selectMaterials: (id: string, materialImageIds: string[] | null) =>
    request<TaskDetail>(`/api/tasks/${id}/select-materials`, {
      method: "POST",
      body: JSON.stringify({ material_image_ids: materialImageIds }),
    }),

  generate: (
    id: string,
    designIdea: string,
    numCandidates: number,
    useReference: boolean,
  ) =>
    request<TaskDetail>(`/api/tasks/${id}/generate`, {
      method: "POST",
      body: JSON.stringify({
        design_idea: designIdea,
        num_candidates: numCandidates,
        use_reference: useReference,
      }),
    }),

  retry: (id: string) =>
    request<TaskDetail>(`/api/tasks/${id}/retry`, { method: "POST" }),

  deleteTask: (id: string) => request<void>(`/api/tasks/${id}`, { method: "DELETE" }),

  bulkDeleteTasks: (taskIds: string[]) =>
    request<{ deleted: number; not_found: string[] }>("/api/tasks/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ task_ids: taskIds }),
    }),

  // ---- 能力配置 ----
  settings: () => request<SettingsView>("/api/settings"),

  updateSettings: (values: Record<string, unknown>) =>
    request<SettingsView>("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ values }),
    }),

  resetSettings: () => request<SettingsView>("/api/settings", { method: "DELETE" }),

  cacheStats: () => request<IdentifyCacheStats>("/api/cache/identify/stats"),

  clearCache: (model?: string) =>
    request<{ removed: number }>(
      `/api/cache/identify${model ? `?model=${encodeURIComponent(model)}` : ""}`,
      { method: "DELETE" },
    ),
};

export const taskEventsUrl = (id: string) => `${API_BASE}/api/tasks/${id}/events`;
export const boardStreamUrl = () => `${API_BASE}/api/events/stream`;

export type { ClothingImage, DesignImage, TaskDetail, TaskSummary };
