"use client";

import { useEffect, useRef, useState } from "react";
import { api, formatDuration, mediaUrl, type Background, type BackgroundTask } from "@/lib/api";
import { Alert, Button, Card, EmptyState, Field, Input, NumberInput, ProgressBar, Spinner } from "./ui";

function BackgroundCard({ bg, onDelete }: { bg: Background; onDelete: () => void }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [confirm, setConfirm] = useState(false);
  return (
    <article className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <div className="relative aspect-video bg-zinc-950">
        <video
          ref={ref}
          src={mediaUrl(`/media/backgrounds/${bg.file}`)}
          poster={bg.thumb ? mediaUrl(`/media/backgrounds/${bg.thumb}`) : undefined}
          muted
          loop
          playsInline
          preload="metadata"
          className="h-full w-full object-cover"
          onMouseEnter={() => ref.current?.play().catch(() => {})}
          onMouseLeave={() => ref.current?.pause()}
        />
        <span className="absolute right-1.5 bottom-1.5 rounded bg-black/75 px-1 py-px font-mono text-[10px] text-white">
          {formatDuration(bg.duration)}
        </span>
      </div>
      <div className="p-3">
        <p className="line-clamp-2 text-xs font-medium leading-snug text-zinc-900" title={bg.title}>
          {bg.title}
        </p>
        <p className="mt-0.5 truncate text-[11px] text-zinc-500">
          {bg.channel ?? "Uploaded file"} · {bg.size_mb} MB
        </p>
        <div className="mt-2 flex items-center justify-between">
          {bg.url ? (
            <a href={bg.url} target="_blank" rel="noreferrer" className="text-[11px] font-medium text-zinc-500 hover:text-zinc-900 hover:underline">
              Source
            </a>
          ) : (
            <span />
          )}
          {confirm ? (
            <span className="flex gap-1">
              <button type="button" onClick={onDelete} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-red-700 hover:bg-red-50">
                Delete
              </button>
              <button type="button" onClick={() => setConfirm(false)} className="rounded px-1.5 py-0.5 text-[11px] text-zinc-500 hover:bg-zinc-100">
                Cancel
              </button>
            </span>
          ) : (
            <button type="button" onClick={() => setConfirm(true)} className="rounded px-1.5 py-0.5 text-[11px] text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900">
              Remove
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

export function Backgrounds({ onChange }: { onChange?: () => void }) {
  const [items, setItems] = useState<Background[] | null>(null);
  const [task, setTask] = useState<BackgroundTask | null>(null);
  const [count, setCount] = useState(12);
  const [link, setLink] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .backgrounds()
      .then((r) => {
        setItems(r.items);
        setTask(r.task);
      })
      .catch((e: Error) => setError(e.message));
  }, [reloadKey]);

  // While a download runs, poll its progress; reload the list when it finishes.
  const running = task?.running ?? false;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      api
        .backgroundStatus()
        .then((s) => {
          setTask(s);
          if (!s.running) {
            setReloadKey((k) => k + 1);
            onChange?.();
          }
        })
        .catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [running, onChange]);

  async function act(fn: () => Promise<BackgroundTask>) {
    setError(null);
    try {
      setTask(await fn());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      await api.uploadBackground(file);
      setReloadKey((k) => k + 1);
      onChange?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteBackground(id);
      setItems((list) => list?.filter((b) => b.id !== id) ?? null);
      onChange?.();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const totalMb = items?.reduce((s, b) => s + b.size_mb, 0) ?? 0;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_1fr]">
      <div className="space-y-4 lg:sticky lg:top-20 lg:h-fit">
        <Card
          title="Add backgrounds"
          description="Used by the Blurred background and Split screen layouts. Each clip gets a random one, cut to the clip's length."
        >
          <div className="space-y-4">
            <div>
              <Field label="Download random free-to-use videos" hint="Gameplay and satisfying videos whose uploader marks them as no-copyright. About 2 minutes each, video only.">
                <div className="flex gap-2">
                  <NumberInput min={1} max={30} value={count} onChange={setCount} className="w-20" />
                  <Button className="flex-1 whitespace-nowrap" disabled={running} onClick={() => act(() => api.downloadBackgrounds(count))}>
                    Download
                  </Button>
                </div>
              </Field>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (link.trim()) act(() => api.addBackgroundLink(link.trim())).then(() => setLink(""));
              }}
            >
              <Field label="Add from a YouTube link" hint="A random 2 minute section is taken.">
                <div className="flex gap-2">
                  <Input value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
                  <Button type="submit" disabled={running || !link.trim()}>
                    Add
                  </Button>
                </div>
              </Field>
            </form>

            <div>
              <input
                ref={fileRef}
                type="file"
                accept="video/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              />
              <Button className="w-full" loading={uploading} onClick={() => fileRef.current?.click()}>
                Upload a video file
              </Button>
            </div>

            {task && (task.running || task.error || task.total > 0) && (
              <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
                <div className="mb-1.5 flex justify-between text-xs">
                  <span className="font-medium text-zinc-700">
                    {task.running ? "Downloading" : task.error ? "Failed" : `Added ${task.added}`}
                  </span>
                  <span className="font-mono text-zinc-500">
                    {task.done} / {task.total}
                  </span>
                </div>
                <ProgressBar
                  value={task.total ? task.done / task.total : 0}
                  indeterminate={task.running && task.done === 0}
                  tone={task.error ? "danger" : !task.running ? "success" : "default"}
                />
                {task.running && task.current && <p className="mt-1.5 truncate text-[11px] text-zinc-500">{task.current}</p>}
                {task.error && <p className="mt-1.5 text-xs text-red-700">{task.error}</p>}
              </div>
            )}
          </div>
        </Card>
        <p className="px-1 text-xs leading-relaxed text-zinc-500">
          “No copyright” is the uploader’s claim. Check the source link if you are unsure about a video.
        </p>
      </div>

      <section className="min-w-0">
        {error && (
          <div className="mb-4">
            <Alert>{error}</Alert>
          </div>
        )}
        {!items ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner /> Loading backgrounds
          </div>
        ) : items.length === 0 ? (
          <EmptyState title="No background videos yet">Download some random ones, add a link, or upload a file.</EmptyState>
        ) : (
          <>
            <div className="mb-3">
              <h2 className="text-base font-semibold text-zinc-900">Backgrounds</h2>
              <p className="text-xs text-zinc-500">
                {items.length} videos · {Math.round(totalMb)} MB · hover to preview
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
              {items.map((bg) => (
                <BackgroundCard key={bg.id} bg={bg} onDelete={() => remove(bg.id)} />
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
