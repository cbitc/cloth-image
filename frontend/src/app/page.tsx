"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { SelectableImageGrid } from "@/components/SelectableImageGrid";
import { Button, Card, EmptyState, ErrorText, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { ClothingImage, SiteOption } from "@/lib/types";

export default function SearchPage() {
  const router = useRouter();
  const [sites, setSites] = useState<SiteOption[]>([]);
  const [selectedSites, setSelectedSites] = useState<string[]>([]);
  const [query, setQuery] = useState("真丝连衣裙");
  const [count, setCount] = useState(24);

  const [images, setImages] = useState<ClothingImage[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [searching, setSearching] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<string>("");

  const [designIdea, setDesignIdea] = useState("");
  const [autoGenerate, setAutoGenerate] = useState(false);
  const [requireMaterialSelection, setRequireMaterialSelection] = useState(true);

  useEffect(() => {
    api
      .listSites()
      .then((data) => {
        setSites(data.sites);
        setMode(data.mode);
        setSelectedSites(data.sites.slice(0, 1).map((site) => site.id));
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const pickedImages = useMemo(
    () => images.filter((image) => picked.has(image.id)),
    [images, picked],
  );

  async function handleSearch() {
    setError(null);
    setSearching(true);
    try {
      const data = await api.searchClothing({
        sites: selectedSites,
        query,
        count,
      });
      setImages(data.images);
      setPicked(new Set());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSearching(false);
    }
  }

  async function handleCreate() {
    if (pickedImages.length === 0) return;
    setError(null);
    setCreating(true);
    try {
      await api.createTasks({
        clothing_image_ids: pickedImages.map((image) => image.id),
        design_idea: designIdea,
        auto_generate: autoGenerate,
        require_material_selection: requireMaterialSelection,
      });
      router.push("/tasks");
    } catch (err) {
      setError((err as Error).message);
      setCreating(false);
    }
  }

  function toggleSite(id: string) {
    setSelectedSites((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  function togglePick(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-5 pb-32">
      <Card>
        <SectionTitle hint={mode ? `provider: ${mode}` : undefined}>
          1 · 搜索服装图
        </SectionTitle>

        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="space-y-3">
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">搜索关键词</label>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="例如：真丝连衣裙 / 秋冬大衣"
                className="w-full rounded-xl border border-white/10 bg-ink-950/70 px-3 py-2 text-sm outline-none focus:border-sky-400/60"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-xs text-slate-400">
                目标网站（可多选，可设置寻找的网站）
              </label>
              <div className="flex flex-wrap gap-2">
                {sites.map((site) => {
                  const active = selectedSites.includes(site.id);
                  return (
                    <button
                      key={site.id}
                      type="button"
                      onClick={() => toggleSite(site.id)}
                      className={`rounded-xl border px-3 py-1.5 text-xs transition ${
                        active
                          ? "border-sky-400/60 bg-sky-500/15 text-sky-200"
                          : "border-white/10 text-slate-400 hover:border-white/25"
                      }`}
                    >
                      {site.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <div>
              <label className="mb-1.5 block text-xs text-slate-400">
                数量：<span className="text-sky-300">{count}</span> 张
              </label>
              <input
                type="range"
                min={6}
                max={60}
                step={6}
                value={count}
                onChange={(event) => setCount(Number(event.target.value))}
                className="h-1 w-full accent-sky-400"
              />
            </div>
            <Button onClick={handleSearch} disabled={searching} className="w-full">
              {searching ? <Spinner /> : null}
              {searching ? "搜索中…" : "搜索服装图"}
            </Button>
            <p className="text-[11px] leading-relaxed text-slate-500">
              每张被选中的图片将创建一个独立任务，任务之间并发执行、互不阻塞。
            </p>
          </div>
        </div>

        {error ? <div className="mt-3"><ErrorText>{error}</ErrorText></div> : null}
      </Card>

      <Card>
        <SectionTitle hint={images.length ? `共 ${images.length} 张，已选 ${picked.size} 张` : undefined}>
          2 · 从结果中选择（点选创建任务）
        </SectionTitle>
        {images.length === 0 ? (
          <EmptyState>还没有结果，先在上方搜索服装图</EmptyState>
        ) : (
          <SelectableImageGrid
            images={images.map((image) => ({
              id: image.id,
              thumbnail_url: image.thumbnail_url,
              image_url: image.image_url,
              caption: image.title,
              meta: image.site,
            }))}
            selectedIds={picked}
            onToggle={togglePick}
          />
        )}
      </Card>

      {picked.size > 0 ? (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-white/10 bg-ink-900/95 backdrop-blur">
          <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-6 py-3">
            <span className="text-sm">
              已选 <span className="font-semibold text-sky-300">{picked.size}</span> 张 → 将创建{" "}
              <span className="font-semibold text-sky-300">{picked.size}</span> 个任务
            </span>
            <input
              value={designIdea}
              onChange={(event) => setDesignIdea(event.target.value)}
              placeholder="设计想法（可稍后在任务页填写）"
              className="min-w-[240px] flex-1 rounded-xl border border-white/10 bg-ink-950/70 px-3 py-2 text-sm outline-none focus:border-sky-400/60"
            />
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={requireMaterialSelection}
                onChange={(event) => setRequireMaterialSelection(event.target.checked)}
                className="accent-sky-400"
              />
              人工挑选面料图
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={autoGenerate}
                onChange={(event) => setAutoGenerate(event.target.checked)}
                className="accent-sky-400"
              />
              确认材质后自动生成
            </label>
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? <Spinner /> : null}
              创建任务
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
