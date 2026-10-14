"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/Pipeline";
import { Button, Card, EmptyState, ProgressBar, Spinner } from "@/components/ui";
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
  const { tasks, connected } = useBoardTasks([]);

  useEffect(() => {
    api
      .listTasks()
      .then(setInitial)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const list = tasks.length > 0 ? tasks : initial;
  const filtered = list.filter((task) => matches(task, filter));

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-sm font-semibold text-slate-200">任务看板</h1>
          <span className="text-xs text-slate-500">
            共 {list.length} 个任务 · {connected ? "实时推送已连接" : "轮询/首屏数据"}
          </span>
          <div className="ml-auto flex flex-wrap gap-2">
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
            <Link href="/">
              <Button variant="outline" className="!py-1.5 text-xs">
                + 新建任务
              </Button>
            </Link>
          </div>
        </div>
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
            <Link key={task.id} href={`/tasks/${task.id}`}>
              <Card className="h-full transition hover:border-sky-400/40">
                <div className="flex gap-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={task.clothing_image.thumbnail_url}
                    alt={task.clothing_image.title}
                    className="h-24 w-24 shrink-0 rounded-xl object-cover"
                  />
                  <div className="min-w-0 flex-1 space-y-2">
                    <StatusBadge status={task.status} />
                    <p className="truncate text-xs text-slate-300" title={task.clothing_image.title}>
                      {task.clothing_image.title || task.id.slice(0, 8)}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      材质 {task.tag_count} · 面料 {task.material_image_count} · 设计图{" "}
                      {task.design_image_count}
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
                  <p className="mt-2 line-clamp-2 text-[10px] text-rose-400">{task.error}</p>
                ) : null}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
