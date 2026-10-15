"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/Pipeline";
import {
  Button,
  Card,
  EmptyState,
  ErrorText,
  ProgressBar,
  Spinner,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useBoardTasks } from "@/lib/hooks";
import { formatTime, STATUS_PROGRESS } from "@/lib/taskStatus";
import type { TaskSummary, TaskStatus } from "@/lib/types";

const FILTERS: Array<{ key: "all" | "active" | "waiting" | "done" | "failed"; label: string }> = [
  { key: "all", label: "全部" },
  { key: "active", label: "进行中" },
  { key: "waiting", label: "待人工确认" },
  { key: "done", label: "已完成" },
  { key: "failed", label: "失败" },
];

function matches(task: TaskSummary, filter: string): boolean {
  if (filter === "all") return true;
  if (filter === "waiting")
    return ["AWAIT_MATERIAL_CONFIRM", "AWAIT_MATERIAL_SELECT", "AWAIT_DESIGN_IDEA"].includes(
      task.status,
    );
  if (filter === "done") return task.status === "DONE";
  if (filter === "failed") return task.status === "FAILED";
  return ["PENDING", "IDENTIFYING", "MATERIAL_SEARCH", "GENERATING"].includes(task.status);
}

export default function TasksPage() {
  const [initial, setInitial] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { tasks, connected, setTasks } = useBoardTasks([]);

  useEffect(() => {
    api
      .listTasks()
      .then(setInitial)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const list = tasks.length > 0 ? tasks : initial;
  const filtered = list.filter((task) => matches(task, filter));

  const finishedIds = filtered
    .filter((task) => task.status === "DONE" || task.status === "FAILED")
    .map((task) => task.id);
  const allSelected =
    filtered.length > 0 && filtered.every((task) => selected.has(task.id));

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected(allSelected ? new Set() : new Set(filtered.map((task) => task.id)));
  }

  /** 本地先摘掉；SSE 看板流会在 ~1.2s 内再推一次服务端真值 */
  function dropLocally(ids: string[]) {
    const keep = (task: TaskSummary) => !ids.includes(task.id);
    setInitial((prev) => prev.filter(keep));
    setTasks((prev) => prev.filter(keep));
    setSelected((prev) => new Set([...prev].filter((id) => !ids.includes(id))));
  }

  async function handleBulkDelete(ids: string[], label: string) {
    if (ids.length === 0 || busy) return;
    const ok = window.confirm(
      `确认删除 ${ids.length} 个任务（${label}）？\n任务下的材质卡片、面料图与设计图会一并删除，且不可恢复。`,
    );
    if (!ok) return;

    setBusy(true);
    setError(null);
    try {
      const result = await api.bulkDeleteTasks(ids);
      dropLocally(ids);
      if (result.not_found.length > 0) {
        setError(
          `已删除 ${result.deleted} 个；另有 ${result.not_found.length} 个任务已不存在`,
        );
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-sm font-semibold text-slate-200">任务看板</h1>
          <span className="text-xs text-slate-500">
            共 {list.length} 个任务 · {connected ? "实时推送已连接" : "轮询/首屏数据"}
            {selected.size > 0 ? ` · 已选 ${selected.size}` : ""}
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setFilter(item.key)}
                className={`rounded-lg px-3 py-1.5 text-xs transition ${
                  filter === item.key
                    ? "bg-white/10 text-slate-100"
                    : "text-slate-400 hover:bg-white/5"
                }`}
              >
                {item.label}
              </button>
            ))}
            <span className="mx-0.5 h-4 w-px bg-white/10" />
            <Button
              variant="outline"
              className="!py-1.5 text-xs"
              onClick={toggleSelectAll}
              disabled={filtered.length === 0}
            >
              {allSelected ? "取消全选" : "全选当前"}
            </Button>
            <Button
              variant="outline"
              className="!py-1.5 text-xs"
              onClick={() => handleBulkDelete([...selected], "已选中")}
              disabled={busy || selected.size === 0}
            >
              删除选中{selected.size > 0 ? ` (${selected.size})` : ""}
            </Button>
            <Button
              variant="outline"
              className="!py-1.5 text-xs"
              onClick={() => handleBulkDelete(finishedIds, "已完成 / 失败")}
              disabled={busy || finishedIds.length === 0}
            >
              清空已结束{finishedIds.length > 0 ? ` (${finishedIds.length})` : ""}
            </Button>
            <Link href="/">
              <Button variant="outline" className="!py-1.5 text-xs">
                + 新建任务
              </Button>
            </Link>
          </div>
        </div>

        {error ? (
          <div className="mt-3">
            <ErrorText>{error}</ErrorText>
          </div>
        ) : null}
      </Card>

      {loading && list.length === 0 ? (
        <EmptyState>
          <span className="flex items-center gap-2">
            <Spinner /> 加载中…
          </span>
        </EmptyState>
      ) : filtered.length === 0 ? (
        <EmptyState>暂无任务，去「搜索服装图」选几张图创建任务吧</EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((task) => (
            <div key={task.id} className="relative">
              <Link href={`/tasks/${task.id}`}>
                <Card
                  className={`h-full transition hover:border-sky-400/40 ${
                    selected.has(task.id) ? "ring-1 ring-sky-400/50" : ""
                  }`}
                >
                  <div className="flex gap-3">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={task.clothing_image.thumbnail_url}
                      alt={task.clothing_image.title}
                      className="h-24 w-24 shrink-0 rounded-xl object-cover"
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                      <StatusBadge status={task.status} />
                      <p
                        className="truncate text-xs text-slate-300"
                        title={task.clothing_image.title}
                      >
                        {task.clothing_image.title || task.id.slice(0, 8)}
                      </p>
                      <p className="text-[11px] text-slate-500">
                        材质卡片 {task.has_material_card ? "✓" : "—"} · 面料{" "}
                        {task.material_image_count} · 设计图 {task.design_image_count}
                      </p>
                    </div>
                  </div>

                  <div className="mt-3 space-y-1.5">
                    <ProgressBar value={STATUS_PROGRESS[task.status as TaskStatus]} />
                    <div className="flex justify-between text-[10px] text-slate-500">
                      <span>{formatTime(task.created_at)}</span>
                      <span>{task.id.slice(0, 8)}</span>
                    </div>
                  </div>

                  {task.status === "FAILED" && task.error ? (
                    <p className="mt-2 line-clamp-2 text-[10px] text-rose-400">
                      {task.error}
                    </p>
                  ) : null}
                </Card>
              </Link>
              {/* 勾选框放在 Link 之外，避免点选时跳转到详情 */}
              <input
                type="checkbox"
                checked={selected.has(task.id)}
                onChange={() => toggleSelect(task.id)}
                title="选择该任务"
                aria-label={`选择任务 ${task.id.slice(0, 8)}`}
                className="absolute left-3 top-3 z-10 h-4 w-4 cursor-pointer accent-sky-400"
                style={{ background: "rgba(2,6,23,0.7)" }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
