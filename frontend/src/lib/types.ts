// 与后端 app/schemas.py 保持一致的契约类型。

export type TaskStatus =
  | "PENDING"
  | "IDENTIFYING"
  | "AWAIT_MATERIAL_CONFIRM"
  | "MATERIAL_SEARCH"
  | "AWAIT_MATERIAL_SELECT"
  | "AWAIT_DESIGN_IDEA"
  | "GENERATING"
  | "DONE"
  | "FAILED";

export interface ClothingImage {
  id: string;
  image_url: string;
  thumbnail_url: string;
  page_url: string;
  title: string;
  site: string;
  source_query: string;
  provider: string;
}

export interface MaterialTag {
  id: string;
  material: string;
  material_en: string;
  confidence: number;
  evidence: string;
  category: string;
  source: string;
  rank: number;
}

export interface MaterialImage {
  id: string;
  tag: string;
  image_url: string;
  thumbnail_url: string;
  source_url: string;
  similarity: number;
  selected: boolean;
  rank: number;
}

export interface DesignImage {
  id: string;
  image_url: string;
  thumbnail_url: string;
  prompt: string;
  model: string;
  seed: number;
  is_mock: boolean;
  rank: number;
}

export interface TaskEvent {
  id: string;
  stage: string;
  status: string;
  message: string;
  progress: number;
  created_at: string;
}

export interface TaskSummary {
  id: string;
  status: TaskStatus;
  error: string | null;
  design_idea: string;
  auto_generate: boolean;
  require_material_selection: boolean;
  clothing_image: ClothingImage;
  tag_count: number;
  material_image_count: number;
  design_image_count: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskDetail extends TaskSummary {
  material_tags: MaterialTag[];
  material_images: MaterialImage[];
  design_images: DesignImage[];
  events: TaskEvent[];
}

export interface MaterialTagInput {
  material: string;
  material_en?: string;
  confidence?: number;
  evidence?: string;
  category?: string;
}

export interface MaterialTagDef {
  material: string;
  material_en: string;
  category: string;
  gloss: string;
  drape: string;
  keywords: string[];
}

export interface SearchClothingResponse {
  images: ClothingImage[];
  warnings: string[];
}

export interface CreateTasksResponse {
  tasks: TaskSummary[];
}

export interface SiteOption {
  id: string;
  label: string;
}

// --------------------------------------------------------------------------- //
// 能力配置（设置页）
// --------------------------------------------------------------------------- //
export type FieldType = "select" | "text" | "secret" | "int" | "float" | "bool";

export interface FieldSpec {
  name: string;
  label: string;
  group: string;
  type: FieldType;
  choices?: string[];
  option_labels?: Record<string, string>;
  min?: number;
  max?: number;
  pattern?: string;
  help?: string;
}

export interface FieldGroup {
  name: string;
  fields: FieldSpec[];
}

export type AbilityState = "ready" | "stub" | "missing_key";

export interface AbilityStatus {
  ability: string;
  label: string;
  signature: string;
  provider: string;
  options: string[];
  state: AbilityState;
  state_label: string;
  hint: string;
}

export interface SecretState {
  configured: boolean;
  overridden: boolean;
}

export interface SettingsView {
  ability_status: AbilityStatus[];
  groups: FieldGroup[];
  values: Record<string, unknown>;
  secrets: Record<string, SecretState>;
  overridden: string[];
  mode: string;
  abilities: Record<string, string>;
  warnings: string[];
  removed?: number;
}

export interface IdentifyCacheStats {
  entries: number;
  total_hits: number;
  saved_tokens: number;
  models: string[];
}
