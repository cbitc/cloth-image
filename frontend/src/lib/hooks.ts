"use client";

import { useEffect, useRef, useState } from "react";

import { boardStreamUrl, taskEventsUrl } from "./api";
import { isTerminal } from "./taskStatus";
import type { TaskDetail, TaskEvent, TaskSummary } from "./types";

/** 订阅单个任务的 SSE 进度流。
 *
 * `reloadKey` 变化会重新订阅：流在任务到达终态时会自动关闭，
 * 若之后任务又进入非终态（如 DONE → 再生成一版），需要重新订阅才能继续跟踪。
 */
export function useTaskEvents(
  taskId: string,
  initial?: TaskDetail | null,
  reloadKey = 0,
) {
  const [task, setTask] = useState<TaskDetail | null>(initial ?? null);
  const [events, setEvents] = useState<TaskEvent[]>(initial?.events ?? []);
  const closedRef = useRef(false);

  useEffect(() => {
    if (!taskId) return;
    closedRef.current = false;
    const source = new EventSource(taskEventsUrl(taskId));

    source.addEventListener("snapshot", (raw) => {
      const data = JSON.parse((raw as MessageEvent).data) as TaskDetail;
      setTask(data);
      setEvents(data.events ?? []);
      if (isTerminal(data.status)) {
        closedRef.current = true;
        source.close();
      }
    });

    source.addEventListener("event", (raw) => {
      const event = JSON.parse((raw as MessageEvent).data) as TaskEvent;
      setEvents((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event]));
    });

    return () => source.close();
  }, [taskId, reloadKey]);

  return { task, events, setTask };
}

/** 订阅看板任务列表流。 */
export function useBoardTasks(initial: TaskSummary[] = []) {
  const [tasks, setTasks] = useState<TaskSummary[]>(initial);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = new EventSource(boardStreamUrl());
    source.addEventListener("tasks", (raw) => {
      setTasks(JSON.parse((raw as MessageEvent).data) as TaskSummary[]);
      setConnected(true);
    });
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, []);

  return { tasks, connected, setTasks };
}
