"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString("zh-CN");
}

export function AuthBadge() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  if (loading) {
    return <span className="text-xs text-slate-500">检查登录状态…</span>;
  }

  if (!user) {
    return (
      <div className="flex items-center gap-3 text-xs">
        <span className="text-slate-500">未登录</span>
        <Link
          href="/login"
          className="rounded-lg border border-white/10 px-3 py-1.5 text-slate-200 hover:bg-white/5"
        >
          登录
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-slate-400">
        {user.email} · {user.plan}
        {user.trial ? "（试用）" : ""} · 许可至 {formatDate(user.expires_at)}
      </span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          router.push("/login");
        }}
        className="rounded-lg px-2 py-1.5 text-slate-400 hover:bg-white/5 hover:text-slate-100"
      >
        退出
      </button>
    </div>
  );
}
