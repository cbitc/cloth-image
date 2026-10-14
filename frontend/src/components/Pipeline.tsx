"use client";

import { PIPELINE_STEPS, STATUS_LABEL, STATUS_PROGRESS, STATUS_STYLE } from "@/lib/taskStatus";
import type { TaskStatus } from "@/lib/types";

import { ProgressBar } from "./ui";

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_STYLE[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

export function PipelineSteps({ status }: { status: TaskStatus }) {
  const progress = STATUS_PROGRESS[status];
  return (
    <div className="space-y-3">
      <ProgressBar value={progress} />
      <ol className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
        {PIPELINE_STEPS.map((step, index) => {
          const previous = index === 0 ? 0 : PIPELINE_STEPS[index - 1].threshold;
          const done = progress >= step.threshold;
          const active = !done && progress >= previous;
          return (
            <li key={step.key} className="flex items-center gap-2">
              <span
                className={`grid h-5 w-5 place-items-center rounded-full text-[10px] font-bold ${
                  done
                    ? "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40"
                    : active
                      ? "bg-sky-500/20 text-sky-300 ring-1 ring-sky-500/40"
                      : "bg-white/5 text-slate-500"
                }`}
              >
                {done ? "✓" : active ? "•" : "—"}
              </span>
              <span className={done || active ? "text-slate-300" : "text-slate-500"}>
                {step.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
