"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PipelineSteps, StatusBadge } from "@/components/Pipeline";
import { MaterialCardEditor } from "@/components/MaterialCardEditor";
import { ResultGallery } from "@/components/ResultGallery";
import { SelectableImageGrid } from "@/components/SelectableImageGrid";
import { Button, Card, EmptyState, ErrorText, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useTaskEvents } from "@/lib/hooks";
import { formatTime, isTerminal } from "@/lib/taskStatus";
import type { CardOptions, MaterialCardPatch, TaskDetail } from "@/lib/types";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;

  const [reloadKey, setReloadKey] = useState(0);
  const { task, events, setTask } = useTaskEvents(id, null, reloadKey);
  const [cardOptions, setCardOptions] = useState<CardOptions | null>(null);
  const [cardPatch, setCardPatch] = useState<MaterialCardPatch>({});
  const [selectedMaterials, setSelectedMaterials] = useState<Set<string>>(new Set());
  const [designIdea, setDesignIdea] = useState("");
  const [numCandidates, setNumCandidates] = useState(3);
  const [useReference, setUseReference] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const cardSignature = useRef("");
  const materialSignature = useRef("");
  const ideaSignature = useRef("");
  const useRefSignature = useRef<boolean | null>(null);

  useEffect(() => {
    api.cardOptions().then(setCardOptions).catch(() => undefined);
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

  // 服务端卡片变化（或用户点了「修改卡片」）时清空本地草稿
  useEffect(() => {
    if (!task) return;
    const card = task.material_card;
    const signature = card ? `${card.id}:${card.source}:${card.updated_at}` : "";
    if (signature !== cardSignature.current) {
      cardSignature.current = signature;
      setCardPatch({});
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

  // 开关以服务端为准；用户手动切换后（尚未生成，服务端值未变）不会被覆盖
  useEffect(() => {
    if (!task) return;
    if (task.use_reference !== useRefSignature.current) {
      useRefSignature.current = task.use_reference;
      setUseReference(task.use_reference);
    }
  }, [task]);

  async function run(action: () => Promise<TaskDetail>) {
    setBusy(true);
    setError(null);
    try {
      const data = await action();
      setTask(data);
      // 任务回到非终态（例如 DONE 后「再生成一版」）时重新订阅 SSE：
      // 流在到达终态时已关闭，不重订的话界面会一直停在旧状态
      if (!isTerminal(data.status)) setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
      // 多半是本地状态落后于服务端（409 之类）：重新拉一次，让界面回到真实状态
      try {
        setTask(await api.getTask(id));
      } catch {
        /* 任务可能已被删除，忽略 */
      }
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
  const canEditCard = [
    "AWAIT_MATERIAL_CONFIRM",
    "AWAIT_MATERIAL_SELECT",
    "AWAIT_DESIGN_IDEA",
    "DONE",
  ].includes(task.status);
  const card = task.material_card;
  const region = card?.regions[0] ?? null;
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
            <label className="mt-3 flex items-start gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                checked={useReference}
                onChange={(event) => setUseReference(event.target.checked)}
                className="mt-0.5 accent-sky-400"
              />
              <span>
                参考原服装图（保留版型）
                <span className="mt-0.5 block text-[10px] leading-relaxed text-slate-500">
                  取消勾选则不把原图送进模型，仅按材质图与文字描述生成；
                  部分生图实现本身不使用参考图，此时该开关不生效。
                </span>
              </span>
            </label>
            <Button
              className="mt-3 w-full"
              disabled={busy || !canGenerate}
              onClick={() =>
                run(() => api.generate(task.id, designIdea, numCandidates, useReference))
              }
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
            ) : !task.material_card ? (
              <EmptyState>暂无材质卡片</EmptyState>
            ) : canConfirm ? (
              cardOptions ? (
                <>
                  <MaterialCardEditor
                    card={task.material_card}
                    options={cardOptions}
                    patch={cardPatch}
                    onPatchChange={setCardPatch}
                  />
                  <Button
                    className="mt-4 w-full"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        // 先落盘编辑，再确认 → 检索面料图（两步都是幂等的部分更新）
                        if (Object.keys(cardPatch).length) {
                          await api.updateMaterialCard(task.id, cardPatch);
                        }
                        return api.confirmMaterials(task.id);
                      })
                    }
                  >
                    {busy ? <Spinner /> : null}
                    确认材质并检索面料图
                  </Button>
                </>
              ) : (
                <EmptyState>
                  <span className="flex items-center gap-2">
                    <Spinner /> 加载字段选项…
                  </span>
                </EmptyState>
              )
            ) : (
              <div className="space-y-3">
                <dl className="grid gap-x-4 gap-y-2 text-[11px] sm:grid-cols-2">
                  {card && region ? (
                    <>
                      <div className="flex gap-2">
                        <dt className="text-slate-500">品类</dt>
                        <dd className="text-slate-200">{card.category || "—"}</dd>
                      </div>
                      <div className="flex items-center gap-2">
                        <dt className="text-slate-500">主色</dt>
                        <dd className="flex items-center gap-1.5 text-slate-200">
                          <i
                            className="inline-block h-3 w-3 rounded-sm border border-white/20"
                            style={{ backgroundColor: region.color.dominant_hex }}
                          />
                          {region.color.dominant_name || "—"}
                          <span className="text-slate-500">{region.color.dominant_hex}</span>
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="text-slate-500">图案</dt>
                        <dd className="text-slate-200">
                          {region.pattern.type}
                          {region.pattern.scale ? ` · ${region.pattern.scale}` : ""}
                          {region.pattern.direction ? ` · ${region.pattern.direction}` : ""}
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="text-slate-500">光泽</dt>
                        <dd className="text-slate-200">
                          {region.optical.gloss} / {region.optical.transparency}
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="text-slate-500">面料</dt>
                        <dd className="text-slate-200">
                          {region.fabric.material || "—"}
                          {region.fabric.category ? `（${region.fabric.category}）` : ""}
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="text-slate-500">手感</dt>
                        <dd className="text-slate-200">
                          {region.behavior.weight} / {region.behavior.drape}
                          {region.behavior.is_default ? (
                            <span className="ml-1 text-[10px] text-slate-500">默认值</span>
                          ) : null}
                        </dd>
                      </div>
                    </>
                  ) : null}
                </dl>

                {region?.color.palette.length ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] text-slate-400">色板</span>
                    {region.color.palette.map((entry, index) => (
                      <span
                        key={`${entry.hex}-${index}`}
                        className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-slate-300"
                      >
                        <i
                          className="inline-block h-3 w-3 rounded-sm border border-white/20"
                          style={{ backgroundColor: entry.hex }}
                        />
                        {entry.hex} · {Math.round((entry.ratio ?? 0) * 100)}%
                      </span>
                    ))}
                  </div>
                ) : null}

                {card?.swatch.url || card?.swatch.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={card?.swatch.thumbnail_url || card?.swatch.url}
                    alt="材质小样"
                    className="h-20 w-20 rounded-xl border border-white/10 object-cover"
                  />
                ) : null}

                {card?.note ? (
                  <p className="text-[11px] text-slate-300">补充说明：{card.note}</p>
                ) : null}

                {card?.evidence ? (
                  <p className="text-[11px] leading-relaxed text-slate-400">
                    判断依据：{card.evidence}
                  </p>
                ) : null}

                <span className="inline-block rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-slate-400">
                  {card?.source === "user" ? "人工确认" : "AI 识别"}
                  {card ? ` · 总体置信度 ${Math.round(card.overall_confidence * 100)}%` : ""}
                </span>

                {canEditCard ? (
                  <Button
                    variant="outline"
                    className="w-full"
                    disabled={busy}
                    onClick={() => {
                      cardSignature.current = "";
                      setCardPatch({});
                      setTask({ ...task, status: "AWAIT_MATERIAL_CONFIRM" });
                    }}
                  >
                    修改材质卡片（重跑后续步骤）
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
              <EmptyState>确认材质后，将按卡片里的面料名检索面料特写图</EmptyState>
            ) : task.material_images.length > 0 ? (
              <>
                <SelectableImageGrid
                  images={task.material_images.map((image) => ({
                    id: image.id,
                    thumbnail_url: image.thumbnail_url,
                    image_url: image.image_url,
                    caption: image.label,
                    meta:
                      image.origin === "upload"
                        ? "用户上传"
                        : `相似度 ${(image.similarity * 100).toFixed(0)}%`,
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

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <label className="text-[11px] text-slate-400">
                上传面料图（编辑入口 2「换小样」）：
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  disabled={busy || !canEditCard}
                  onChange={(event) => {
                    const files = event.target.files;
                    if (!files || !files.length) return;
                    void run(() => api.uploadMaterialImages(task.id, files));
                    event.target.value = "";
                  }}
                  className="ml-2 text-[11px] text-slate-300 file:mr-2 file:rounded-md file:border-0 file:bg-sky-500/15 file:px-2 file:py-1 file:text-[11px] file:text-sky-300"
                />
              </label>
            </div>
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
