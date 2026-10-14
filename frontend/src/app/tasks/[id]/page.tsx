"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PipelineSteps, StatusBadge } from "@/components/Pipeline";
import { ResultGallery } from "@/components/ResultGallery";
import { SelectableImageGrid } from "@/components/SelectableImageGrid";
import { TagEditor } from "@/components/TagEditor";
import { Button, Card, EmptyState, ErrorText, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useTaskEvents } from "@/lib/hooks";
import { formatTime } from "@/lib/taskStatus";
import type { MaterialTagDef, MaterialTagInput, TaskDetail } from "@/lib/types";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;

  const { task, events, setTask } = useTaskEvents(id);
  const [taxonomy, setTaxonomy] = useState<MaterialTagDef[]>([]);
  const [draftTags, setDraftTags] = useState<MaterialTagInput[]>([]);
  const [selectedMaterials, setSelectedMaterials] = useState<Set<string>>(new Set());
  const [designIdea, setDesignIdea] = useState("");
  const [numCandidates, setNumCandidates] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const tagSignature = useRef("");
  const materialSignature = useRef("");
  const ideaSignature = useRef("");

  useEffect(() => {
    api.taxonomy().then(setTaxonomy).catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await api.getTask(id);
      setTask(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (id) void load();
  }, [id, load]);

  // 后端 tag 变化时同步草稿（用户编辑过程中不会被覆盖）
  useEffect(() => {
    if (!task) return;
    const signature = task.material_tags.map((tag) => `${tag.id}:${tag.material}`).join("|");
    if (signature !== tagSignature.current) {
      tagSignature.current = signature;
      setDraftTags(
        task.material_tags.map((tag) => ({
          material: tag.material,
          material_en: tag.material_en,
          confidence: tag.confidence,
          evidence: tag.evidence,
          category: tag.category,
        })),
      );
    }
  }, [task]);

  useEffect(() => {
    if (!task) return;
    const signature = task.material_images.map((image) => `${image.id}:${image.selected}`).join("|");
    if (signature !== materialSignature.current) {
      materialSignature.current = signature;
      setSelectedMaterials(
        new Set(task.material_images.filter((image) => image.selected).map((image) => image.id)),
      );
    }
  }, [task]);

  useEffect(() => {
    if (!task) return;
    if (task.design_idea && task.design_idea !== ideaSignature.current) {
      ideaSignature.current = task.design_idea;
      setDesignIdea(task.design_idea);
    }
  }, [task]);

  async function run<T>(action: () => Promise<TaskDetail>) {
    setBusy(true);
    setError(null);
    try {
      const data = await action();
      setTask(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const selectedCount = useMemo(
    () => task?.material_images.filter((image) => selectedMaterials.has(image.id)).length ?? 0,
    [task, selectedMaterials],
  );

  if (loading && !task) {
    return (
      <EmptyState>
        <span className="flex items-center gap-2">
          <Spinner /> 加载任务…
        </span>
      </EmptyState>
    );
  }

  if (!task) {
    return (
      <div className="space-y-3">
        <ErrorText>{error ?? "任务不存在"}</ErrorText>
        <Link href="/tasks" className="text-xs text-sky-400">
          ← 返回看板
        </Link>
      </div>
    );
  }

  const canConfirm = task.status === "AWAIT_MATERIAL_CONFIRM";
  const canSelect = task.status === "AWAIT_MATERIAL_SELECT";
  const canGenerate =
    task.status === "AWAIT_DESIGN_IDEA" ||
    task.status === "AWAIT_MATERIAL_SELECT" ||
    task.status === "DONE";
  const inFlight = ["IDENTIFYING", "MATERIAL_SEARCH", "GENERATING", "PENDING"].includes(
    task.status,
  );

  return (
    <div className="space-y-5 pb-10">
      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Link href="/tasks" className="text-xs text-slate-400 hover:text-slate-100">
            ← 看板
          </Link>
          <StatusBadge status={task.status} />
          <span className="font-mono text-[11px] text-slate-500">{task.id}</span>
          <span className="ml-auto text-[11px] text-slate-500">
            更新于 {formatTime(task.updated_at)}
          </span>
        </div>
        <PipelineSteps status={task.status} />
        {task.error ? <div className="mt-3"><ErrorText>{task.error}</ErrorText></div> : null}
        {error ? <div className="mt-3"><ErrorText>{error}</ErrorText></div> : null}
        {task.status === "FAILED" ? (
          <Button className="mt-3" variant="danger" onClick={() => run(() => api.retry(task.id))}>
            重试
          </Button>
        ) : null}
      </Card>

      <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
        <Card className="xl:sticky xl:top-20 xl:self-start">
          <SectionTitle hint={task.clothing_image.site}>原服装图</SectionTitle>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={task.clothing_image.image_url}
            alt={task.clothing_image.title}
            className="w-full rounded-xl object-cover"
          />
          <p className="mt-3 text-xs text-slate-300">{task.clothing_image.title}</p>
          {task.clothing_image.page_url ? (
            <a
              href={task.clothing_image.page_url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block truncate text-[11px] text-sky-400 hover:underline"
            >
              来源页面
            </a>
          ) : null}

          <div className="mt-4 border-t border-white/5 pt-4">
            <SectionTitle>设计想法</SectionTitle>
            <textarea
              value={designIdea}
              onChange={(event) => setDesignIdea(event.target.value)}
              rows={4}
              placeholder="例如：改成收腰版型，裙摆加长到脚踝，保留原袖型"
              className="w-full resize-none rounded-xl border border-white/10 bg-ink-950/70 px-3 py-2 text-xs outline-none focus:border-sky-400/60"
            />
            <div className="mt-3 flex items-center gap-3">
              <label className="text-xs text-slate-400">
                候选数 <span className="text-sky-300">{numCandidates}</span>
              </label>
              <input
                type="range"
                min={1}
                max={6}
                value={numCandidates}
                onChange={(event) => setNumCandidates(Number(event.target.value))}
                className="h-1 flex-1 accent-sky-400"
              />
            </div>
            <Button
              className="mt-3 w-full"
              disabled={busy || !canGenerate}
              onClick={() => run(() => api.generate(task.id, designIdea, numCandidates))}
            >
              {busy ? <Spinner /> : null}
              {task.status === "DONE" ? "再生成一版" : "生成设计图"}
            </Button>
            {!canGenerate ? (
              <p className="mt-2 text-[11px] text-slate-500">
                需先完成材质确认，才能生成设计图。
              </p>
            ) : null}
          </div>
        </Card>

        <div className="space-y-5">
          <Card>
            <SectionTitle hint={canConfirm ? "★ 人工检查点：识别结果可能有误，请确认或修改" : undefined}>
              材质识别结果
            </SectionTitle>

            {task.status === "IDENTIFYING" || task.status === "PENDING" ? (
              <EmptyState>
                <span className="flex items-center gap-2">
                  <Spinner /> 正在识别服装材质…
                </span>
              </EmptyState>
            ) : draftTags.length === 0 ? (
              <EmptyState>暂无材质标签</EmptyState>
            ) : canConfirm ? (
              <>
                <TagEditor tags={draftTags} taxonomy={taxonomy} onChange={setDraftTags} />
                <Button
                  className="mt-4 w-full"
                  disabled={busy || draftTags.every((tag) => !tag.material.trim())}
                  onClick={() =>
                    run(() =>
                      api.confirmMaterials(
                        task.id,
                        draftTags.filter((tag) => tag.material.trim()),
                      ),
                    )
                  }
                >
                  {busy ? <Spinner /> : null}
                  确认材质并检索面料图
                </Button>
              </>
            ) : (
              <div className="space-y-2">
                {task.material_tags.map((tag, index) => (
                  <div
                    key={tag.id}
                    className="rounded-xl border border-white/10 bg-white/[0.03] p-3"
                  >
                    <div className="flex items-center gap-3">
                      <span className="grid h-6 w-6 place-items-center rounded-md bg-sky-500/15 text-[11px] font-bold text-sky-300">
                        {index + 1}
                      </span>
                      <span className="text-sm font-medium text-slate-100">{tag.material}</span>
                      <span className="text-[11px] text-slate-500">{tag.material_en}</span>
                      <span className="ml-auto text-xs font-medium text-sky-300">
                        {Math.round(tag.confidence * 100)}%
                      </span>
                    </div>
                    <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
                      {tag.evidence}
                    </p>
                    {tag.category ? (
                      <span className="mt-2 inline-block rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-slate-400">
                        {tag.category} · {tag.source === "user" ? "人工确认" : "AI 识别"}
                      </span>
                    ) : null}
                  </div>
                ))}
                {task.status === "DONE" || canGenerate ? (
                  <Button
                    variant="outline"
                    className="mt-2 w-full"
                    disabled={busy}
                    onClick={() => {
                      tagSignature.current = "";
                      setDraftTags(
                        task.material_tags.map((tag) => ({
                          material: tag.material,
                          material_en: tag.material_en,
                          confidence: tag.confidence,
                          evidence: tag.evidence,
                          category: tag.category,
                        })),
                      );
                      setTask({ ...task, status: "AWAIT_MATERIAL_CONFIRM" });
                    }}
                  >
                    修改材质标签（重跑后续步骤）
                  </Button>
                ) : null}
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle
              hint={
                task.material_images.length
                  ? `${task.material_images.length} 张${canSelect ? ` · 已选 ${selectedCount} 张` : ""}`
                  : undefined
              }
            >
              材质图（面料小样）
            </SectionTitle>

            {task.status === "MATERIAL_SEARCH" || inFlight ? (
              task.material_images.length === 0 ? (
                <EmptyState>
                  <span className="flex items-center gap-2">
                    <Spinner /> 正在检索面料图…
                  </span>
                </EmptyState>
              ) : null
            ) : null}

            {task.material_images.length === 0 && !inFlight ? (
              <EmptyState>确认材质后，将按 tag 检索面料特写图</EmptyState>
            ) : task.material_images.length > 0 ? (
              <>
                <SelectableImageGrid
                  images={task.material_images.map((image) => ({
                    id: image.id,
                    thumbnail_url: image.thumbnail_url,
                    image_url: image.image_url,
                    caption: image.tag,
                    meta: `相似度 ${(image.similarity * 100).toFixed(0)}%`,
                    badge: image.selected ? "已选" : undefined,
                  }))}
                  selectedIds={selectedMaterials}
                  onToggle={
                    canSelect
                      ? (imageId) =>
                          setSelectedMaterials((prev) => {
                            const next = new Set(prev);
                            if (next.has(imageId)) next.delete(imageId);
                            else next.add(imageId);
                            return next;
                          })
                      : undefined
                  }
                  columns="grid-cols-3 lg:grid-cols-5"
                />
                {canSelect ? (
                  <Button
                    className="mt-4"
                    disabled={busy || selectedCount === 0}
                    onClick={() =>
                      run(() => api.selectMaterials(task.id, Array.from(selectedMaterials)))
                    }
                  >
                    {busy ? <Spinner /> : null}
                    确认 {selectedCount} 张面料图
                  </Button>
                ) : null}
              </>
            ) : null}
          </Card>

          <Card>
            <SectionTitle
              hint={task.design_images.length ? `生成 ${task.design_images.length} 张候选` : undefined}
            >
              设计图
            </SectionTitle>
            {task.status === "GENERATING" ? (
              <EmptyState>
                <span className="flex items-center gap-2">
                  <Spinner /> 正在生成设计图…
                </span>
              </EmptyState>
            ) : task.design_images.length === 0 ? (
              <EmptyState>填写设计想法后点击「生成设计图」</EmptyState>
            ) : (
              <ResultGallery images={task.design_images} />
            )}
          </Card>

          <Card>
            <SectionTitle hint={`${events.length} 条`}>执行日志</SectionTitle>
            <ol className="space-y-1.5">
              {events.map((event) => (
                <li key={event.id} className="flex items-start gap-3 text-[11px]">
                  <span className="w-16 shrink-0 tabular-nums text-slate-600">
                    {new Date(event.created_at).toLocaleTimeString("zh-CN", { hour12: false })}
                  </span>
                  <span className="w-28 shrink-0 text-slate-500">{event.stage}</span>
                  <span className="text-slate-300">{event.message}</span>
                </li>
              ))}
              {events.length === 0 ? (
                <li className="text-[11px] text-slate-500">暂无日志</li>
              ) : null}
            </ol>
          </Card>
        </div>
      </div>
    </div>
  );
}
