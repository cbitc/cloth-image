import type { Metadata } from "next";
import Link from "next/link";

import { AuthBadge } from "@/components/AuthBadge";
import { AuthProvider } from "@/lib/auth";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI 服装辅助设计",
  description: "搜图 → 建任务 → 识别材质 → 检索材质图 → 图生图",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AuthProvider>
          <header className="sticky top-0 z-40 border-b border-white/5 bg-ink-950/85 backdrop-blur">
            <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-6 py-3">
              <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-wide">
                <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-sky-400 to-fuchsia-500 text-xs font-bold text-ink-950">
                  AI
                </span>
                服装辅助设计
              </Link>
              <nav className="flex items-center gap-1 text-sm text-slate-400">
                <Link className="rounded-lg px-3 py-1.5 hover:bg-white/5 hover:text-slate-100" href="/">
                  搜索服装图
                </Link>
                <Link
                  className="rounded-lg px-3 py-1.5 hover:bg-white/5 hover:text-slate-100"
                  href="/tasks"
                >
                  任务看板
                </Link>
                <Link
                  className="rounded-lg px-3 py-1.5 hover:bg-white/5 hover:text-slate-100"
                  href="/settings"
                >
                  能力配置
                </Link>
              </nav>
              <div className="ml-auto flex items-center gap-4">
                <span className="hidden text-xs text-slate-500 lg:inline">
                  首次使用请在「能力配置」中选择实现并填写端点
                </span>
                <AuthBadge />
              </div>
            </div>
          </header>
          <main className="mx-auto max-w-[1600px] px-6 py-6">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
