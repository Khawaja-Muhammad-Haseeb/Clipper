"use client";

import { useEffect, useState } from "react";
import { api, type LibraryDetail, type LibraryItem } from "@/lib/api";
import { ClipList } from "./ClipCard";
import { Alert, Button, EmptyState, Spinner, cx } from "./ui";

export function Library({ initialSlug, onReclip }: { initialSlug?: string | null; onReclip: (source: string) => void }) {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(initialSlug ?? null);
  const [detail, setDetail] = useState<LibraryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    api
      .library()
      .then((r) => {
        setError(null);
        setItems(r.items);
        setSelected((cur) => cur ?? r.items[0]?.slug ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, [reloadKey]);

  useEffect(() => {
    if (!selected) return;
    api
      .libraryItem(selected)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [selected, reloadKey]);

  const loadingDetail = selected !== null && detail?.slug !== selected;
  const load = () => setReloadKey((k) => k + 1);

  if (error) return <Alert>{error}</Alert>;
  if (!items)
    return (
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        <Spinner /> Loading library
      </div>
    );
  if (!items.length)
    return <EmptyState title="No clips yet">Clips you generate will appear here.</EmptyState>;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[300px_1fr]">
      <aside className="h-fit rounded-lg border border-zinc-200 bg-white lg:sticky lg:top-20">
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
          <h2 className="text-sm font-semibold">Videos</h2>
          <Button size="sm" variant="ghost" onClick={load}>
            Refresh
          </Button>
        </div>
        <ul className="max-h-[70vh] divide-y divide-zinc-100 overflow-y-auto">
          {items.map((it) => (
            <li key={it.slug}>
              <button
                type="button"
                onClick={() => setSelected(it.slug)}
                className={cx(
                  "flex w-full gap-3 px-4 py-3 text-left transition-colors",
                  selected === it.slug ? "bg-zinc-100" : "hover:bg-zinc-50",
                )}
              >
                {it.thumbnail ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={it.thumbnail} alt="" className="h-10 w-[72px] shrink-0 rounded object-cover" />
                ) : (
                  <div className="h-10 w-[72px] shrink-0 rounded bg-zinc-200" />
                )}
                <div className="min-w-0">
                  <p className="line-clamp-2 text-xs font-medium leading-snug text-zinc-900">{it.title}</p>
                  <p className="mt-0.5 text-[11px] text-zinc-500">
                    {it.clip_count} clips · {new Date(it.updated * 1000).toLocaleDateString()}
                  </p>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="min-w-0">
        {loadingDetail && !detail ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner /> Loading clips
          </div>
        ) : detail ? (
          <>
            <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold text-zinc-900">{detail.title}</h2>
                <p className="text-xs text-zinc-500">
                  {detail.source_video.channel ? `${detail.source_video.channel} · ` : ""}
                  {detail.clips.length} clips
                </p>
              </div>
              <div className="flex items-center gap-3">
                {detail.source_video.url && (
                  <a
                    href={detail.source_video.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-medium text-zinc-600 hover:text-zinc-900 hover:underline"
                  >
                    Open source video
                  </a>
                )}
                {detail.can_reclip && (
                  <Button
                    size="sm"
                    title="Uses the saved transcript. The video is downloaded again only for cutting."
                    onClick={() => onReclip(detail.source_video.source || detail.source_video.url || "")}
                  >
                    Make new clips
                  </Button>
                )}
              </div>
            </div>
            <ClipList slug={detail.slug} clips={detail.clips} />
          </>
        ) : null}
      </section>
    </div>
  );
}
