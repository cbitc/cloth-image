"use client";

import { useState } from "react";

import { Button, Spinner } from "@/components/ui";
import type {
  CardOptions,
  MaterialCard,
  MaterialCardPatch,
  PaletteEntry,
  RegionPatch,
} from "@/lib/types";

/**
 * 用户选定的主色在「颜色重排」里的权重：首选色主导，其余色板项均分剩下的部分。
 * 后端 `rerank.target_labs` 按 ratio 加权算 LAB ΔE，故改 ratio 就等于改重排倾向。
 */
const PRIMARY_COLOR_WEIGHT = 0.6;

const inputClass =
  "w-full rounded-lg border border-white/10 bg-ink-950/70 px-2.5 py-1.5 text-xs outline-none focus:border-sky-400/60";

function paletteForPrimary(hex: string, palette: PaletteEntry[]): PaletteEntry[] {
  const picked = hex.toUpperCase();
  const others = palette.filter((entry) => entry.hex.toUpperCase() !== picked);
  if (!others.length) return [{ hex, ratio: 1 }];

  const share = Number(((1 - PRIMARY_COLOR_WEIGHT) / others.length).toFixed(4));
  return [
    { hex, ratio: PRIMARY_COLOR_WEIGHT },
    ...others.map((entry) => ({ hex: entry.hex, ratio: share })),
  ];
}

/**
 * 「检索条件」面板：让用户显式挑选决定面料图检索的字段（面料 / 图案 / 光泽 / 主色）。
 *
 * - **默认继承识别结果**：局部草稿由卡片初始化；父级用 `key={card.id}:{updated_at}`
 *   让服务端卡片一变就重挂载，因此不会残留过期草稿。
 * - 提交时**只 diff 出真正改过的字段**（后端是部分更新语义，没传的字段保留识别值）。
 * - 条件最终落在材质卡片上，检索与颜色重排都从卡片读取，故这里不需要额外状态。
 */
export function MaterialSearchCriteria({
  card,
  options,
  busy,
  onSubmit,
}: {
  card: MaterialCard;
  options: CardOptions;
  busy: boolean;
  onSubmit: (patch: MaterialCardPatch) => void;
}) {
  const region = card.regions[0];

  const [material, setMaterial] = useState(region?.fabric.material ?? "");
  const [patternType, setPatternType] = useState(region?.pattern.type ?? "");
  const [gloss, setGloss] = useState(region?.optical.gloss ?? "");
  const [hex, setHex] = useState(region?.color.dominant_hex ?? "");

  if (!region) return null;

  const palette = region.color.palette;
  const changed =
    material !== region.fabric.material ||
    patternType !== region.pattern.type ||
    gloss !== region.optical.gloss ||
    hex !== region.color.dominant_hex;

  const buildPatch = (): MaterialCardPatch => {
    const regionPatch: RegionPatch = {};
    if (material !== region.fabric.material) regionPatch.fabric = { material };
    if (patternType !== region.pattern.type) regionPatch.pattern = { type: patternType };
    if (gloss !== region.optical.gloss) regionPatch.optical = { gloss };
    if (hex !== region.color.dominant_hex) {
      regionPatch.color = {
        dominant_hex: hex,
        palette: paletteForPrimary(hex, palette),
      };
    }
    return Object.keys(regionPatch).length ? { region: regionPatch } : {};
  };

  const reset = () => {
    setMaterial(region.fabric.material);
    setPatternType(region.pattern.type);
    setGloss(region.optical.gloss);
    setHex(region.color.dominant_hex);
  };

  const isPrimary = (value: string) => value.toUpperCase() === hex.toUpperCase();

  return (
    <div className="mb-4 rounded-xl border border-white/10 bg-ink-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className="text-xs font-medium text-slate-200">检索条件</span>
        <span className="text-[10px] text-slate-500">
          默认继承识别结果；改动后重新检索，检索词与颜色匹配都按这里来
        </span>
        <button
          type="button"
          disabled={busy || !changed}
          onClick={reset}
          className="ml-auto text-[10px] text-sky-400 hover:underline disabled:text-slate-600 disabled:no-underline"
        >
          恢复识别值
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block space-y-1">
          <span className="text-[11px] text-slate-400">面料（检索主锚）</span>
          <select
            value={material}
            onChange={(event) => setMaterial(event.target.value)}
            className={inputClass}
          >
            {!options.material.includes(material) ? (
              <option value={material}>{material || "（未识别）"}</option>
            ) : null}
            {options.material.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1">
          <span className="text-[11px] text-slate-400">图案</span>
          <select
            value={patternType}
            onChange={(event) => setPatternType(event.target.value)}
            className={inputClass}
          >
            {!options.pattern_type.includes(patternType) ? (
              <option value={patternType}>{patternType || "（未识别）"}</option>
            ) : null}
            {options.pattern_type.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1">
          <span className="text-[11px] text-slate-400">光泽</span>
          <select
            value={gloss}
            onChange={(event) => setGloss(event.target.value)}
            className={inputClass}
          >
            {!options.gloss.includes(gloss) ? (
              <option value={gloss}>{gloss || "（未识别）"}</option>
            ) : null}
            {options.gloss.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1">
          <span className="text-[11px] text-slate-400">主色</span>
          <span className="flex items-center gap-2">
            <input
              type="color"
              value={hex || "#000000"}
              onChange={(event) => setHex(event.target.value.toUpperCase())}
              className="h-8 w-10 shrink-0 cursor-pointer rounded border border-white/10 bg-transparent"
            />
            <input
              value={hex}
              placeholder="#RRGGBB"
              onChange={(event) => setHex(event.target.value.toUpperCase())}
              className={inputClass}
            />
          </span>
        </label>
      </div>

      {palette.length ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-slate-400">识别色板（点选设为主色）</span>
          {palette.map((entry, index) => (
            <button
              key={`${entry.hex}-${index}`}
              type="button"
              title="设为主色"
              onClick={() => setHex(entry.hex.toUpperCase())}
              className={`flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] transition ${
                isPrimary(entry.hex)
                  ? "bg-sky-500/20 text-sky-200 ring-1 ring-sky-400/40"
                  : "bg-white/5 text-slate-300 hover:bg-white/10"
              }`}
            >
              <i
                className="inline-block h-3 w-3 rounded-sm border border-white/20"
                style={{ backgroundColor: entry.hex }}
              />
              {entry.hex}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={() => onSubmit(buildPatch())}>
          {busy ? <Spinner /> : null}
          {changed ? "按这些条件重新检索" : "重新检索面料图"}
        </Button>
        <span className="text-[10px] text-slate-500">
          重新检索会替换现有检索结果（你自己上传的面料图会保留）。
        </span>
      </div>
    </div>
  );
}
