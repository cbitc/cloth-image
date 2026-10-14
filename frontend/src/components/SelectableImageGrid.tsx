"use client";

export interface GridImage {
  id: string;
  thumbnail_url: string;
  image_url: string;
  caption?: string;
  badge?: string;
  meta?: string;
}

export function SelectableImageGrid({
  images,
  selectedIds,
  onToggle,
  columns = "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6",
}: {
  images: GridImage[];
  selectedIds: Set<string>;
  onToggle?: (id: string) => void;
  columns?: string;
}) {
  return (
    <div className={`grid gap-3 ${columns}`}>
      {images.map((image) => {
        const selected = selectedIds.has(image.id);
        return (
          <button
            key={image.id}
            type="button"
            onClick={() => onToggle?.(image.id)}
            className={`group relative overflow-hidden rounded-xl border text-left transition ${
              selected
                ? "border-sky-400 ring-2 ring-sky-400/50"
                : "border-white/10 hover:border-white/30"
            }`}
            title={image.caption}
          >
            {/* 占位图来自后端，直接用 <img> 避免额外域名配置 */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={image.thumbnail_url}
              alt={image.caption ?? image.id}
              className="aspect-square w-full object-cover"
              loading="lazy"
            />
            {selected ? (
              <span className="absolute right-2 top-2 grid h-6 w-6 place-items-center rounded-full bg-sky-500 text-xs font-bold text-ink-950">
                ✓
              </span>
            ) : null}
            {image.badge ? (
              <span className="absolute left-2 top-2 rounded-md bg-black/65 px-1.5 py-0.5 text-[10px] text-slate-100">
                {image.badge}
              </span>
            ) : null}
            {image.caption || image.meta ? (
              <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-2 py-1.5">
                <span className="block truncate text-[11px] text-slate-100">
                  {image.caption}
                </span>
                {image.meta ? (
                  <span className="block truncate text-[10px] text-slate-400">{image.meta}</span>
                ) : null}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
