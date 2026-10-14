"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { FieldEditor } from "@/components/SettingField";
import { Button, Card, EmptyState, ErrorText, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type {
  AbilityState,
  FieldSpec,
  IdentifyCacheStats,
  SettingsView,
} from "@/lib/types";

const STATE_STYLE: Record<AbilityState, string> = {
  ready: "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40",
  missing_key: "bg-rose-500/20 text-rose-300 ring-1 ring-rose-500/40",
};

export default function SettingsPage() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [secretInputs, setSecretInputs] = useState<Record<string, string>>({});
  const [clearedSecrets, setClearedSecrets] = useState<string[]>([]);
  const [cache, setCache] = useState<IdentifyCacheStats | null>(null);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const data = await api.settings();
    setView(data);
    setDraft({ ...data.values });
    setSecretInputs({});
    setClearedSecrets([]);
    api.cacheStats().then(setCache).catch(() => undefined);
  }, []);

  useEffect(() => {
    load()
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [load]);

  const fieldSpecs = useMemo(() => {
    const map: Record<string, FieldSpec> = {};
    for (const group of view?.groups ?? []) {
      for (const field of group.fields) map[field.name] = field;
    }
    return map;
  }, [view]);

  /** 能力配置组的字段画在能力卡片内，不在通用表单里重复出现 */
  const abilityFields = useMemo(
    () => view?.groups.find((group) => group.name === "能力配置")?.fields ?? [],
    [view],
  );

  const overridden = useMemo(() => new Set(view?.overridden ?? []), [view]);

  /** 条件字段：仅当依赖项取值命中时显示（如选中真实 provider 才显示端点/Key/模型） */
  function visible(spec: FieldSpec): boolean {
    if (!spec.show_when) return true;
    return Object.entries(spec.show_when).every(([dep, allowed]) =>
      allowed.map(String).includes(String(draft[dep] ?? "")),
    );
  }

  function setValue(name: string, value: unknown) {
    setDraft((prev) => ({ ...prev, [name]: value }));
  }

  function setSecret(name: string, value: string) {
    setSecretInputs((prev) => ({ ...prev, [name]: value }));
    setClearedSecrets((prev) => prev.filter((item) => item !== name));
  }

  function clearSecret(name: string) {
    setSecretInputs((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
    setClearedSecrets((prev) => (prev.includes(name) ? prev : [...prev, name]));
  }

  /** 只提交改动项：未改动的字段保持"跟随环境变量"，不会被写成覆盖 */
  function buildPatch(): Record<string, unknown> {
    const patch: Record<string, unknown> = {};
    if (!view) return patch;

    for (const [name, value] of Object.entries(draft)) {
      if (name in secretInputs) continue;
      if (JSON.stringify(value) !== JSON.stringify(view.values[name])) {
        patch[name] = value;
      }
    }
    for (const [name, raw] of Object.entries(secretInputs)) {
      if (raw.trim()) patch[name] = raw.trim();
    }
    for (const name of clearedSecrets) patch[name] = null;

    return patch;
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const patch = buildPatch();
      if (Object.keys(patch).length === 0) {
        setNotice("没有检测到改动");
        return;
      }
      const data = await api.updateSettings(patch);
      setView(data);
      setDraft({ ...data.values });
      setSecretInputs({});
      setClearedSecrets([]);
      setNotice(`已保存 ${Object.keys(patch).length} 项配置，立即生效`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const data = await api.resetSettings();
      setView(data);
      setDraft({ ...data.values });
      setSecretInputs({});
      setClearedSecrets([]);
      setNotice(`已重置 ${data.removed ?? 0} 项覆盖，回退到环境变量`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleClearCache() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.clearCache();
      setCache(await api.cacheStats());
      setNotice(`已清空识别缓存 ${result.removed} 条`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !view) {
    return (
      <EmptyState>
        <span className="flex items-center gap-2">
          <Spinner /> 加载配置…
        </span>
      </EmptyState>
    );
  }

  if (!view) {
    return <ErrorText>{error ?? "无法加载配置"}</ErrorText>;
  }

  return (
    <div className="space-y-5 pb-24">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-sm font-semibold text-slate-200">能力配置</h1>
          <span className="text-xs text-slate-500">
            修改立即生效并持久化；未改动的项继续跟随环境变量
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="outline" onClick={handleReset} disabled={busy}>
              重置为环境变量
            </Button>
            <Button onClick={handleSave} disabled={busy}>
              {busy ? <Spinner /> : null}
              保存配置
            </Button>
          </div>
        </div>

        {error ? (
          <div className="mt-3">
            <ErrorText>{error}</ErrorText>
          </div>
        ) : null}
        {notice ? (
          <p className="mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            {notice}
          </p>
        ) : null}

        {view.warnings.length ? (
          <ul className="mt-3 space-y-1.5">
            {view.warnings.map((warning) => (
              <li
                key={warning}
                className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
              >
                {warning}
              </li>
            ))}
          </ul>
        ) : null}

        <p className="mt-3 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2 text-[11px] leading-relaxed text-slate-500">
          安全提示：当前服务未启用鉴权，能访问本页的人都可以修改配置并写入密钥。
          密钥不会被回传（只显示是否已配置），但仍建议仅在本机或内网使用；
          对外暴露前请设置 <code className="text-slate-400">SETTINGS_WRITE_ENABLED=false</code> 或补充鉴权。
        </p>
      </Card>

      <Card>
        <SectionTitle hint="每项能力显式选择实现并填写端点；搜索类能力暂无真实实现">
          四个能力
        </SectionTitle>
        <div className="grid gap-4 lg:grid-cols-2">
          {view.ability_status.map((item) => {
            const providerSpec = fieldSpecs[`${item.ability}_provider`];
            const extraFields = abilityFields.filter(
              (field) =>
                field.name.startsWith(`${item.ability}_`) &&
                field.name !== `${item.ability}_provider`,
            );
            return (
              <div
                key={item.ability}
                className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-slate-100">{item.label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${STATE_STYLE[item.state]}`}
                  >
                    {item.state_label}
                  </span>
                  <span className="ml-auto font-mono text-[11px] text-slate-500">
                    {item.provider}
                  </span>
                </div>
                <p className="font-mono text-[11px] text-slate-500">{item.signature}</p>
                {providerSpec ? (
                  <FieldEditor
                    spec={providerSpec}
                    value={draft[providerSpec.name]}
                    overridden={overridden.has(providerSpec.name)}
                    onChange={setValue}
                    onSecretChange={setSecret}
                    onSecretClear={clearSecret}
                  />
                ) : (
                  <p className="rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-1.5 text-[11px] text-slate-500">
                    仅 Mock（暂无真实实现）
                  </p>
                )}
                {extraFields.filter(visible).map((spec) => (
                  <FieldEditor
                    key={spec.name}
                    spec={spec}
                    value={draft[spec.name]}
                    secret={view.secrets[spec.name]}
                    secretInput={secretInputs[spec.name]}
                    overridden={overridden.has(spec.name)}
                    onChange={setValue}
                    onSecretChange={setSecret}
                    onSecretClear={clearSecret}
                  />
                ))}
                {item.hint ? (
                  <p className="text-[11px] text-slate-500">{item.hint}</p>
                ) : null}
              </div>
            );
          })}
        </div>
      </Card>

      {view.groups
        .filter((group) => group.name !== "能力配置")
        .map((group) => (
          <Card key={group.name}>
            <SectionTitle>{group.name}</SectionTitle>
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {group.fields.map((spec) => (
                <FieldEditor
                  key={spec.name}
                  spec={spec}
                  value={draft[spec.name]}
                  secret={view.secrets[spec.name]}
                  secretInput={secretInputs[spec.name]}
                  overridden={overridden.has(spec.name)}
                  onChange={setValue}
                  onSecretChange={setSecret}
                  onSecretClear={clearSecret}
                />
              ))}
            </div>
          </Card>
        ))}

      <Card>
        <SectionTitle hint="相同图片 + 相同模型时跳过模型调用">
          识别结果缓存
        </SectionTitle>
        {cache ? (
          <div className="flex flex-wrap items-center gap-6 text-sm">
            <span className="text-slate-400">
              条目 <span className="text-slate-100">{cache.entries}</span>
            </span>
            <span className="text-slate-400">
              累计命中 <span className="text-slate-100">{cache.total_hits}</span>
            </span>
            <span className="text-slate-400">
              估算省下 <span className="text-emerald-300">{cache.saved_tokens}</span> tokens
            </span>
            <span className="text-[11px] text-slate-500">
              {cache.models.length ? `模型：${cache.models.join(", ")}` : "暂无缓存"}
            </span>
            <Button
              variant="outline"
              className="ml-auto"
              onClick={handleClearCache}
              disabled={busy || cache.entries === 0}
            >
              清空缓存
            </Button>
          </div>
        ) : (
          <p className="text-xs text-slate-500">暂无缓存数据</p>
        )}
      </Card>
    </div>
  );
}
