"use client";

import { useState } from "react";

import type { DesignImage } from "@/lib/types";

export function ResultGallery({ images }: { images: DesignImage[] }) {
  const [preview, setPreview] = useState<DesignImage | null>(null);

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {images.map((image, index) => (
          <button
            key={image.id}
            type="button"
            onClick={() => setPreview(image)}
            className="group overflow-hidden rounded-2xl border border-white/10 text-left transition hover:border-sky-400/60"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={image.image_url}
              alt={`设计图 ${index + 1}`}
              className="aspect-square w-full object-cover transition group-hover:scale-[1.02]"
            />
            <div className="flex items-center justify-between gap-2 px-3 py-2 text-[11px] text-slate-400">
              <span className="flex shrink-0 items-center gap-2">
                候选 {index + 1}
                <span
                  className={`rounded-md px-1.5 py-0.5 text-[10px] ${
                    image.used_reference
                      ? "bg-sky-500/15 text-sky-300"
                      : "bg-amber-500/15 text-amber-300"
                  }`}
                  title={
                    image.used_reference
                      ? "生成时把原服装图作为参考图送进了模型"
                      : "生成时没有使用原服装图（仅材质图 + 文字描述）"
                  }
                >
                  {image.used_reference ? "参考原图" : "纯材质生成"}
                </span>
              </span>
              <span className="truncate">
                {image.model} · seed {image.seed}
              </span>
            </div>
          </button>
        ))}
      </div>

      {preview ? (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-6"
          onClick={() => setPreview(null)}
          role="presentation"
        >
          <div className="max-h-full w-full max-w-3xl overflow-auto rounded-2xl border border-white/10 bg-ink-900 p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={preview.image_url}
              alt="设计图预览"
              className="w-full rounded-xl object-contain"
            />
            <pre className="mt-3 whitespace-pre-wrap rounded-xl bg-black/40 p-3 text-[11px] leading-relaxed text-slate-300">
              {preview.prompt}
            </pre>
            <p className="mt-2 text-[11px] text-slate-500">
              {preview.used_reference
                ? "生成时参考了原服装图"
                : "生成时未参考原服装图（仅材质图 + 文字描述）"}
              <span className="ml-3">点击任意处关闭</span>
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
