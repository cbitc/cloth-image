"use client";

import type { FieldSpec } from "@/lib/types";

export function FieldEditor({
  spec,
  value,
  secret,
  secretInput,
  overridden,
  onChange,
  onSecretChange,
  onSecretClear,
}: {
  spec: FieldSpec;
  value: unknown;
  secret?: { configured: boolean; overridden: boolean };
  secretInput?: string;
  overridden: boolean;
  onChange: (name: string, value: unknown) => void;
  onSecretChange: (name: string, value: string) => void;
  onSecretClear: (name: string) => void;
}) {
  const inputClass =
    "w-full rounded-xl border border-white/10 bg-ink-950/70 px-3 py-2 text-sm outline-none focus:border-sky-400/60";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-300">{spec.label}</label>
        {overridden ? (
          <span
            className="rounded-md bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-300"
            title="该项已被设置页覆盖，优先于环境变量"
          >
            已覆盖
          </span>
        ) : null}
      </div>

      {spec.type === "bool" ? (
        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(spec.name, event.target.checked)}
            className="accent-sky-400"
          />
          {Boolean(value) ? "已开启" : "已关闭"}
        </label>
      ) : spec.type === "select" ? (
        <select
          value={String(value ?? "")}
          onChange={(event) => onChange(spec.name, event.target.value)}
          className={inputClass}
        >
          {(spec.choices ?? []).map((choice) => (
            <option key={choice || "__inherit__"} value={choice}>
              {spec.option_labels?.[choice] ?? (choice || "（跟随全局）")}
            </option>
          ))}
        </select>
      ) : spec.type === "secret" ? (
        <div className="flex items-center gap-2">
          <input
            type="password"
            value={secretInput ?? ""}
            placeholder={secret?.configured ? "已配置（留空则不修改）" : "未配置"}
            onChange={(event) => onSecretChange(spec.name, event.target.value)}
            className={inputClass}
            autoComplete="off"
          />
          {secret?.configured || secret?.overridden ? (
            <button
              type="button"
              onClick={() => onSecretClear(spec.name)}
              className="shrink-0 rounded-lg border border-white/10 px-2 py-1.5 text-[11px] text-slate-300 hover:bg-white/5"
            >
              清除
            </button>
          ) : null}
        </div>
      ) : spec.type === "int" || spec.type === "float" ? (
        <input
          type="number"
          value={value === null || value === undefined ? "" : String(value)}
          min={spec.min}
          max={spec.max}
          step={spec.type === "float" ? 0.5 : 1}
          onChange={(event) => {
            const raw = event.target.value;
            onChange(spec.name, raw === "" ? "" : Number(raw));
          }}
          className={inputClass}
        />
      ) : (
        <input
          value={value === null || value === undefined ? "" : String(value)}
          placeholder={spec.placeholder ?? ""}
          onChange={(event) => onChange(spec.name, event.target.value)}
          className={inputClass}
        />
      )}

      {spec.help ? (
        <p className="text-[11px] leading-relaxed text-slate-500">{spec.help}</p>
      ) : null}
      {spec.min !== undefined && spec.max !== undefined ? (
        <p className="text-[11px] text-slate-600">
          取值范围 {spec.min} ~ {spec.max}
        </p>
      ) : null}
    </div>
  );
}
