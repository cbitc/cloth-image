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

// --------------------------------------------------------------------------- //
// 材质卡片（与后端 app/schemas.py 的 MaterialCardOut 等保持一致）
// --------------------------------------------------------------------------- //
export interface PaletteEntry {
  hex: string;
  ratio: number;
}

export interface ColorInfo {
  dominant_hex: string;
  dominant_name: string;
  lab: number[] | null;
  palette: PaletteEntry[];
  distribution: string;
}

export interface PatternInfo {
  type: string;
  scale: string;
  direction: string;
  layout: string;
}

export interface OpticalInfo {
  gloss: string;
  transparency: string;
}

export interface FabricInfo {
  material: string;
  material_en: string;
  category: string;
  finish: string;
  confidence: number;
}

export interface BehaviorInfo {
  weight: string;
  drape: string;
  confidence: number;
  is_default: boolean;
}

export interface RegionConfidence {
  color: number;
  pattern: number;
  gloss: number;
}

export interface Swatch {
  url: string;
  thumbnail_url: string;
  crop_box: number[] | null;
  texture_embedding_ref: string;
}

export interface MaterialRegion {
  region_id: string;
  region_type: string;
  color: ColorInfo;
  pattern: PatternInfo;
  optical: OpticalInfo;
  fabric: FabricInfo;
  behavior: BehaviorInfo;
  confidence: RegionConfidence;
}

export interface MaterialCard {
  id: string;
  task_id: string;
  /** ai = 模型识别结果；user = 用户编辑/确认过的 */
  source: string;
  category: string;
  regions: MaterialRegion[];
  evidence: string;
  note: string;
  schema_version: string;
  overall_confidence: number;
  swatch: Swatch;
  updated_at: string;
}

// 卡片编辑入口 1「改属性」：局部更新，只传改过的字段
export interface ColorPatch {
  dominant_hex?: string;
  dominant_name?: string;
  palette?: PaletteEntry[];
  distribution?: string;
}

export interface PatternPatch {
  type?: string;
  scale?: string;
  direction?: string;
  layout?: string;
}

export interface OpticalPatch {
  gloss?: string;
  transparency?: string;
}

export interface FabricPatch {
  material?: string;
  material_en?: string;
  category?: string;
  finish?: string;
}

export interface BehaviorPatch {
  weight?: string;
  drape?: string;
}

export interface RegionPatch {
  color?: ColorPatch;
  pattern?: PatternPatch;
  optical?: OpticalPatch;
  fabric?: FabricPatch;
  behavior?: BehaviorPatch;
}

export interface MaterialCardPatch {
  category?: string;
  /** 编辑入口 3「写文字」：编译进生图提示词 */
  note?: string;
  evidence?: string;
  region?: RegionPatch;
}

/** 后端下发的受控取值（图案 5 类 / 光泽 4 档 / 品类 / 面料名 …） */
export interface CardOptions {
  category: string[];
  pattern_type: string[];
  gloss: string[];
  transparency: string[];
  weight: string[];
  drape: string[];
  material: string[];
}

export interface MaterialImage {
  id: string;
  /** 检索结果 = 材质名；上传 = 「上传的面料图」 */
  label: string;
  image_url: string;
  thumbnail_url: string;
  source_url: string;
  similarity: number;
  selected: boolean;
  rank: number;
  /** search = 按卡片检索；upload = 用户上传 */
  origin: string;
}

export interface DesignImage {
  id: string;
  image_url: string;
  thumbnail_url: string;
  prompt: string;
  model: string;
  seed: number;
  rank: number;
  /** 该候选是否真的把原服装图作为参考图送进了模型 */
  used_reference: boolean;
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
  /** 生成设计图时是否参考原服装图 */
  use_reference: boolean;
  clothing_image: ClothingImage;
  /** 是否已识别出材质卡片 */
  has_material_card: boolean;
  material_image_count: number;
  design_image_count: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskDetail extends TaskSummary {
  material_card: MaterialCard | null;
  material_images: MaterialImage[];
  design_images: DesignImage[];
  events: TaskEvent[];
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
export type FieldType =
  | "select"
  | "text"
  | "textarea"
  | "secret"
  | "int"
  | "float"
  | "bool";

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
  placeholder?: string;
  /** 仅当依赖字段取值命中时才显示，如 {"material_identifier_provider": ["openai_compatible"]} */
  show_when?: Record<string, string[]>;
  help?: string;
}

export interface FieldGroup {
  name: string;
  fields: FieldSpec[];
}

export type AbilityState = "ready" | "missing_key" | "unconfigured";

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

// --------------------------------------------------------------------------- //
// 登录 / 许可（与后端 app/schemas.py 的 AuthStatusOut 一致）
// --------------------------------------------------------------------------- //
export interface AuthUser {
  authenticated: boolean;
  email: string;
  product: string;
  /** 订阅版本（后端把旧版签发方的 edition 归一到这里） */
  plan: string;
  trial: boolean;
  expires_at: string;
}
