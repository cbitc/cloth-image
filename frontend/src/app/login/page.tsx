"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button, Card, ErrorText, Spinner } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const HINTS: Record<string, string> = {
  SUBSCRIPTION_REQUIRED: "当前账号没有有效订阅，请联系管理员开通后再登录。",
  LICENSE_NOT_CONFIGURED:
    "服务端未配置许可证验签密钥（ENTITLEMENT_LICENSE_JWT_SECRET），请联系管理员。",
  ENTITLEMENT_UNAVAILABLE: "登录服务暂不可用，请稍后再试。",
};

function describe(err: unknown): string {
  if (err instanceof ApiError) return HINTS[err.code ?? ""] ?? err.detail;
  return (err as Error).message;
}

const inputClass =
  "mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500/60";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, refresh } = useAuth();

  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  async function handleRequest(event: FormEvent) {
    event.preventDefault();
    const value = email.trim();
    if (!/.+@.+\..+/.test(value)) {
      setError("请输入有效的邮箱地址");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.requestLogin(value);
      setEmail(value);
      setStep("code");
      setNotice("验证码已发送，5 分钟内有效。");
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleVerify(event: FormEvent) {
    event.preventDefault();
    const value = code.trim();
    if (!/^\d{6}$/.test(value)) {
      setError("请输入 6 位数字验证码");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.verifyLogin(email, value);
      await refresh();
      router.replace("/");
    } catch (err) {
      setError(describe(err));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md pt-10">
      <Card className="space-y-5">
        <div>
          <h1 className="text-base font-semibold text-slate-100">登录</h1>
          <p className="mt-1 text-xs text-slate-500">
            用邮箱验证码登录后可查询当前账号的订阅 / 许可状态。
          </p>
        </div>

        {step === "email" ? (
          <form onSubmit={handleRequest} className="space-y-4">
            <label className="block text-xs text-slate-400">
              邮箱
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                className={inputClass}
              />
            </label>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? <Spinner /> : null}
              发送验证码
            </Button>
          </form>
        ) : (
          <form onSubmit={handleVerify} className="space-y-4">
            <div className="text-xs text-slate-400">
              验证码已发送至 <span className="text-slate-200">{email}</span>
            </div>
            <label className="block text-xs text-slate-400">
              6 位验证码
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
                placeholder="000000"
                className={`${inputClass} tracking-[0.4em]`}
              />
            </label>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? <Spinner /> : null}
              登录并查询许可
            </Button>
            <button
              type="button"
              onClick={() => {
                setStep("email");
                setCode("");
                setError(null);
                setNotice(null);
              }}
              className="w-full text-xs text-slate-500 hover:text-slate-300"
            >
              修改邮箱 / 重新发送
            </button>
          </form>
        )}

        {notice ? <p className="text-xs text-emerald-300">{notice}</p> : null}
        {error ? <ErrorText>{error}</ErrorText> : null}
      </Card>

      <p className="mt-4 text-center text-xs text-slate-500">
        <Link href="/" className="hover:text-slate-300">
          返回首页
        </Link>
      </p>
    </div>
  );
}
