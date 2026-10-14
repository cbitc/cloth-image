import type { TaskStatus } from "./types";

export const STATUS_LABEL: Record<TaskStatus, string> = {
  PENDING: "排队中",
  IDENTIFYING: "识别材质中",
  AWAIT_MATERIAL_CONFIRM: "待确认材质",
  MATERIAL_SEARCH: "检索面料中",
  AWAIT_MATERIAL_SELECT: "待挑选面料",
  AWAIT_DESIGN_IDEA: "待填写想法",
  GENERATING: "生成设计中",
  DONE: "已完成",
  FAILED: "失败",
};

export const STATUS_STYLE: Record<TaskStatus, string> = {
  PENDING: "bg-slate-700/60 text-slate-200",
  IDENTIFYING: "bg-sky-500/20 text-sky-300 ring-1 ring-sky-500/40",
  AWAIT_MATERIAL_CONFIRM: "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/40",
  MATERIAL_SEARCH: "bg-sky-500/20 text-sky-300 ring-1 ring-sky-500/40",
  AWAIT_MATERIAL_SELECT: "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/40",
  AWAIT_DESIGN_IDEA: "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/40",
  GENERATING: "bg-fuchsia-500/20 text-fuchsia-300 ring-1 ring-fuchsia-500/40",
  DONE: "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40",
  FAILED: "bg-rose-500/20 text-rose-300 ring-1 ring-rose-500/40",
};

export const STATUS_PROGRESS: Record<TaskStatus, number> = {
  PENDING: 0,
  IDENTIFYING: 0.15,
  AWAIT_MATERIAL_CONFIRM: 0.3,
  MATERIAL_SEARCH: 0.45,
  AWAIT_MATERIAL_SELECT: 0.6,
  AWAIT_DESIGN_IDEA: 0.7,
  GENERATING: 0.85,
  DONE: 1,
  FAILED: 1,
};

export const WAITING_STATUSES: TaskStatus[] = [
  "AWAIT_MATERIAL_CONFIRM",
  "AWAIT_MATERIAL_SELECT",
  "AWAIT_DESIGN_IDEA",
];

export const TERMINAL_STATUSES: TaskStatus[] = ["DONE", "FAILED"];

export const PIPELINE_STEPS = [
  { key: "identify", label: "识别材质", threshold: 0.15 },
  { key: "material", label: "检索面料", threshold: 0.45 },
  { key: "select", label: "挑选面料", threshold: 0.6 },
  { key: "generate", label: "生成设计图", threshold: 0.85 },
];

export const isWaiting = (status: TaskStatus) => WAITING_STATUSES.includes(status);
export const isTerminal = (status: TaskStatus) => TERMINAL_STATUSES.includes(status);

export function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", { hour12: false });
}
