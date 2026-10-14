"use client";

import { Button } from "./ui";
import type { MaterialTagDef, MaterialTagInput } from "@/lib/types";

export function TagEditor({
  tags,
  taxonomy,
  onChange,
}: {
  tags: MaterialTagInput[];
  taxonomy: MaterialTagDef[];
  onChange: (tags: MaterialTagInput[]) => void;
}) {
  const update = (index: number, patch: Partial<MaterialTagInput>) => {
    onChange(tags.map((tag, i) => (i === index ? { ...tag, ...patch } : tag)));
  };

  const remove = (index: number) => {
    onChange(tags.filter((_, i) => i !== index));
  };

  const add = () => {
    onChange([
      ...tags,
      { material: "", material_en: "", confidence: 0.5, evidence: "", category: "" },
    ]);
  };

  return (
    <div className="space-y-3">
      <datalist id="material-taxonomy">
        {taxonomy.map((item) => (
          <option key={item.material} value={item.material}>
            {item.material_en} · {item.category}
          </option>
        ))}
      </datalist>

      {tags.map((tag, index) => {
        const def = taxonomy.find((item) => item.material === tag.material);
        return (
          <div
            key={index}
            className="rounded-xl border border-white/10 bg-white/[0.03] p-3 space-y-2"
          >
            <div className="flex items-center gap-2">
              <span className="grid h-6 w-6 place-items-center rounded-md bg-sky-500/15 text-[11px] font-bold text-sky-300">
                {index + 1}
              </span>
              <input
                list="material-taxonomy"
                value={tag.material}
                placeholder="材质标签（可搜索词表或自定义）"
                onChange={(event) => {
                  const material = event.target.value;
                  const matched = taxonomy.find((item) => item.material === material);
                  update(index, {
                    material,
                    material_en: matched?.material_en ?? tag.material_en ?? "",
                    category: matched?.category ?? tag.category ?? "",
                  });
                }}
                className="flex-1 rounded-lg border border-white/10 bg-ink-950/70 px-2.5 py-1.5 text-sm outline-none focus:border-sky-400/60"
              />
              <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => remove(index)}>
                删除
              </Button>
            </div>

            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((tag.confidence ?? 0) * 100)}
                onChange={(event) =>
                  update(index, { confidence: Number(event.target.value) / 100 })
                }
                className="h-1 flex-1 accent-sky-400"
              />
              <span className="w-12 text-right text-xs tabular-nums text-sky-300">
                {Math.round((tag.confidence ?? 0) * 100)}%
              </span>
              {def ? (
                <span className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] text-slate-400">
                  光泽 {def.gloss} · 垂坠 {def.drape}
                </span>
              ) : null}
            </div>

            <input
              value={tag.evidence ?? ""}
              placeholder="判断依据（光泽 / 垂坠感 / 织纹…）"
              onChange={(event) => update(index, { evidence: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-ink-950/70 px-2.5 py-1.5 text-xs text-slate-300 outline-none focus:border-sky-400/60"
            />
          </div>
        );
      })}

      <Button variant="outline" onClick={add} className="w-full">
        + 添加材质标签
      </Button>
    </div>
  );
}
