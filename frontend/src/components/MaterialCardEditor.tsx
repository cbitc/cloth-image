"use client";

import type {
  BehaviorPatch,
  CardOptions,
  ColorPatch,
  FabricPatch,
  MaterialCard,
  MaterialCardPatch,
  MaterialRegion,
  OpticalPatch,
  PatternPatch,
  RegionPatch,
} from "@/lib/types";

/** 低于该置信度的字段在 UI 标黄，引导用户人工确认（MVP 计划 §3.2） */
const LOW_CONFIDENCE = 0.7;

const inputClass =
  "w-full rounded-lg border border-white/10 bg-ink-950/70 px-2.5 py-1.5 text-xs outline-none focus:border-sky-400/60";

function ConfidenceTag({ value }: { value: number }) {
  const low = value < LOW_CONFIDENCE;
  return (
    <span
      className={`ml-1 rounded px-1 text-[10px] tabular-nums ${
        low ? "bg-amber-500/20 text-amber-300" : "bg-white/5 text-slate-500"
      }`}
      title={low ? "置信度偏低，建议人工确认" : "模型置信度"}
    >
      {Math.round(value * 100)}%{low ? " 待确认" : ""}
    </span>
  );
}

function Field({
  label,
  confidence,
  children,
}: {
  label: string;
  confidence?: number;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] text-slate-400">
        {label}
        {confidence !== undefined ? <ConfidenceTag value={confidence} /> : null}
      </span>
      {children}
    </label>
  );
}

export function MaterialCardEditor({
  card,
  options,
  patch,
  onPatchChange,
}: {
  card: MaterialCard;
  options: CardOptions;
  patch: MaterialCardPatch;
  onPatchChange: (patch: MaterialCardPatch) => void;
}) {
  const region: MaterialRegion | undefined = card.regions[0];
  if (!region) {
    return <p className="text-xs text-slate-500">卡片没有区域数据，请重试识别。</p>;
  }

  const rp: RegionPatch = patch.region ?? {};
  // 服务端值 + 本地草稿（草稿优先，未改过的字段直接显示服务端值）
  const color = { ...region.color, ...(rp.color ?? {}) };
  const pattern = { ...region.pattern, ...(rp.pattern ?? {}) };
  const optical = { ...region.optical, ...(rp.optical ?? {}) };
  const fabric = { ...region.fabric, ...(rp.fabric ?? {}) };
  const behavior = { ...region.behavior, ...(rp.behavior ?? {}) };
  const category = patch.category ?? card.category;

  const update = (next: RegionPatch) => {
    onPatchChange({ ...patch, region: { ...rp, ...next } });
  };
  const setColor = (value: ColorPatch) =>
    update({ color: { ...(rp.color ?? {}), ...value } });
  const setPattern = (value: PatternPatch) =>
    update({ pattern: { ...(rp.pattern ?? {}), ...value } });
  const setOptical = (value: OpticalPatch) =>
    update({ optical: { ...(rp.optical ?? {}), ...value } });
  const setFabric = (value: FabricPatch) =>
    update({ fabric: { ...(rp.fabric ?? {}), ...value } });
  const setBehavior = (value: BehaviorPatch) =>
    update({ behavior: { ...(rp.behavior ?? {}), ...value } });

  const setDominant = (hex: string) => {
    // 改主色时同步色板首项，避免「主色 ≠ 色板首位」的自相矛盾
    const palette = color.palette.length
      ? [{ ...color.palette[0], hex }, ...color.palette.slice(1)]
      : [{ hex, ratio: 1 }];
    setColor({ dominant_hex: hex, palette });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-4">
        {card.swatch.url || card.swatch.thumbnail_url ? (
          <figure className="w-28 shrink-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={card.swatch.thumbnail_url || card.swatch.url}
              alt="材质小样"
              className="h-28 w-28 rounded-xl border border-white/10 object-cover"
            />
            <figcaption className="mt-1 text-center text-[10px] text-slate-500">
              材质小样（保真锚点）
            </figcaption>
          </figure>
        ) : null}

        <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
          <Field label="品类">
            <select
              value={category}
              onChange={(event) =>
                onPatchChange({ ...patch, category: event.target.value })
              }
              className={inputClass}
            >
              {!options.category.includes(category) ? (
                <option value={category}>{category || "（未识别）"}</option>
              ) : null}
              {options.category.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>

          <Field label="主色" confidence={region.confidence.color}>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={color.dominant_hex || "#000000"}
                onChange={(event) => setDominant(event.target.value.toUpperCase())}
                className="h-8 w-10 cursor-pointer rounded border border-white/10 bg-transparent"
              />
              <input
                value={color.dominant_hex}
                placeholder="#RRGGBB"
                onChange={(event) => setDominant(event.target.value.toUpperCase())}
                className={inputClass}
              />
            </div>
          </Field>

          <Field label="主色名称">
            <input
              value={color.dominant_name}
              placeholder="如 深灰蓝"
              onChange={(event) =>
                setColor({ dominant_name: event.target.value })
              }
              className={inputClass}
            />
          </Field>

          <Field label="颜色分布">
            <input
              value={color.distribution}
              placeholder="如 整体均匀 / 自上而下渐变"
              onChange={(event) => setColor({ distribution: event.target.value })}
              className={inputClass}
            />
          </Field>

          <Field label="图案">
            <select
              value={pattern.type}
              onChange={(event) => setPattern({ type: event.target.value })}
              className={inputClass}
            >
              {!options.pattern_type.includes(pattern.type) ? (
                <option value={pattern.type}>{pattern.type || "（未识别）"}</option>
              ) : null}
              {options.pattern_type.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>

          <Field label="图案尺度 / 方向">
            <div className="flex gap-2">
              <input
                value={pattern.scale}
                placeholder="尺度 如 条宽约 0.8cm"
                onChange={(event) => setPattern({ scale: event.target.value })}
                className={inputClass}
              />
              <input
                value={pattern.direction}
                placeholder="方向 如 竖条纹"
                onChange={(event) => setPattern({ direction: event.target.value })}
                className={inputClass}
              />
            </div>
          </Field>

          <Field label="光泽" confidence={region.confidence.gloss}>
            <select
              value={optical.gloss}
              onChange={(event) => setOptical({ gloss: event.target.value })}
              className={inputClass}
            >
              {!options.gloss.includes(optical.gloss) ? (
                <option value={optical.gloss}>{optical.gloss || "（未识别）"}</option>
              ) : null}
              {options.gloss.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>

          <Field label="透明度">
            <select
              value={optical.transparency}
              onChange={(event) => setOptical({ transparency: event.target.value })}
              className={inputClass}
            >
              {!options.transparency.includes(optical.transparency) ? (
                <option value={optical.transparency}>
                  {optical.transparency || "（未识别）"}
                </option>
              ) : null}
              {options.transparency.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="面料（检索面料图的锚点）"
            confidence={fabric.confidence || undefined}
          >
            <input
              list="material-taxonomy"
              value={fabric.material}
              placeholder="从受控词表选择或自定义"
              onChange={(event) => setFabric({ material: event.target.value })}
              className={inputClass}
            />
          </Field>

          <Field label="手感（重量 / 垂坠，本期为默认值）">
            <div className="flex gap-2">
              <select
                value={behavior.weight}
                onChange={(event) => setBehavior({ weight: event.target.value })}
                className={inputClass}
              >
                {options.weight.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <select
                value={behavior.drape}
                onChange={(event) => setBehavior({ drape: event.target.value })}
                className={inputClass}
              >
                {options.drape.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </div>
          </Field>
        </div>
      </div>

      {color.palette.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-slate-400">色板</span>
          {color.palette.map((entry, index) => (
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

      <datalist id="material-taxonomy">
        {options.material.map((item) => (
          <option key={item} value={item} />
        ))}
      </datalist>

      <Field label="补充说明（编译进生图提示词）">
        <textarea
          value={patch.note ?? card.note}
          rows={2}
          placeholder="如：面料要更挺括一点、领口保持原色"
          onChange={(event) => onPatchChange({ ...patch, note: event.target.value })}
          className={`${inputClass} resize-none`}
        />
      </Field>

      {card.evidence ? (
        <p className="text-[11px] leading-relaxed text-slate-400">
          判断依据：{card.evidence}
        </p>
      ) : null}
    </div>
  );
}
