"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  formatCount,
  formatDate,
  formatDuration,
  type Channel,
  type ClipFormat,
  type Job,
  type LibraryDetail,
  type Video,
  type VideoPage,
} from "@/lib/api";
import { ClipList } from "./ClipCard";
import { JobProgress } from "./JobProgress";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, NumberInput, Segmented, Spinner, cx } from "./ui";

type Mode = "search" | "direct";
type PlainFormat = "crop" | "blur" | "original";
type Layout = "background" | "split";

const FORMAT_HINT: Record<ClipFormat, string> = {
  crop: "Centre-crop to 9:16. Best for a single speaker. Cuts off the sides.",
  blur: "Full frame, full width, on a blurred copy of itself.",
  original: "Keep the original aspect ratio.",
  background: "Full clip, full width, centred over a blurred background video.",
  split: "Full clip in the top half, background video in the bottom half.",
};

function LayoutOption({ value, selected, onSelect }: { value: Layout; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cx(
        "flex items-center gap-3 rounded-md border p-2.5 text-left transition-colors",
        selected ? "border-zinc-900 ring-1 ring-zinc-900" : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
      )}
    >
      {/* Mini 9:16 diagram: dark = your clip, grey = background video */}
      {value === "background" ? (
        <span className="relative flex h-[56px] w-8 shrink-0 items-center overflow-hidden rounded-sm bg-zinc-300">
          <span className="h-[18px] w-full bg-zinc-800" />
        </span>
      ) : (
        <span className="flex h-[56px] w-8 shrink-0 flex-col overflow-hidden rounded-sm">
          <span className="flex flex-1 items-center bg-zinc-200">
            <span className="h-[18px] w-full bg-zinc-800" />
          </span>
          <span className="flex-1 bg-zinc-400" />
        </span>
      )}
      <span className="text-xs font-medium text-zinc-900">{value === "background" ? "Blurred background" : "Split screen"}</span>
    </button>
  );
}

export function NewJob({
  onOpenLibrary,
  initialSource,
  backgroundCount,
}: {
  onOpenLibrary: (slug: string) => void;
  initialSource?: string;
  backgroundCount: number | null;
}) {
  // Source (a re-clip from the Library opens this with the source pre-filled)
  const [mode, setMode] = useState<Mode>(initialSource ? "direct" : "search");
  const [youtuber, setYoutuber] = useState("");
  const [topic, setTopic] = useState("");
  const [count, setCount] = useState(5);
  const [direct, setDirect] = useState(initialSource ?? "");
  const [uploading, setUploading] = useState(false);

  // Search results
  const [channelQuery, setChannelQuery] = useState<string | null>(null);
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [channel, setChannel] = useState<Channel | null>(null);
  const [page, setPage] = useState<VideoPage | null>(null);
  const [checkedTopic, setCheckedTopic] = useState("");
  const [selected, setSelected] = useState<Video | null>(null);
  const [showUnmatched, setShowUnmatched] = useState(false);
  const [busy, setBusy] = useState<null | "channels" | "videos">(null);

  // Settings
  const [minClips, setMinClips] = useState(5);
  const [maxClips, setMaxClips] = useState(7);
  const [minLen, setMinLen] = useState(20);
  const [maxLen, setMaxLen] = useState(60);
  const [plainFormat, setPlainFormat] = useState<PlainFormat>("crop");
  const [useBackground, setUseBackground] = useState(false);
  const [layout, setLayout] = useState<Layout>("background");
  const hasBackgrounds = (backgroundCount ?? 0) > 0;
  const format: ClipFormat = useBackground && hasBackgrounds ? layout : plainFormat;
  const [fresh, setFresh] = useState(Boolean(initialSource));
  const [keepSource, setKeepSource] = useState(false);

  // Job
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<LibraryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const youtuberRef = useRef<HTMLInputElement>(null);
  const topicRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);

  // Resume a job that is still running (e.g. after a page refresh).
  useEffect(() => {
    api.currentJob().then((j) => j && j.status === "running" && setJob(j)).catch(() => {});
  }, []);

  // Poll the running job.
  const jobId = job?.id;
  const jobRunning = job?.status === "running";
  useEffect(() => {
    if (!jobId || !jobRunning) return;
    const t = setInterval(() => {
      api.job(jobId).then(setJob).catch(() => {});
    }, 1000);
    return () => clearInterval(t);
  }, [jobId, jobRunning]);

  // Load the finished clips.
  const doneSlug = job?.status === "done" ? job.result?.slug : null;
  useEffect(() => {
    if (!doneSlug) return;
    api.libraryItem(doneSlug).then(setResult).catch((e: Error) => setError(e.message));
  }, [doneSlug]);

  async function loadVideos(ch: Channel, start: number, t = topic) {
    setBusy("videos");
    setError(null);
    setSelected(null);
    setShowUnmatched(false);
    try {
      const p = await api.videos(ch, t.trim(), start, count);
      setPage(p);
      setCheckedTopic(t.trim());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function chooseChannel(ch: Channel) {
    setChannel(ch);
    await loadVideos(ch, 1);
  }

  async function search() {
    if (!youtuber.trim()) return youtuberRef.current?.focus();
    if (!topic.trim()) return topicRef.current?.focus();
    // Same YouTuber, new topic or count: re-check the videos without searching channels again.
    if (channel && channelQuery === youtuber.trim()) return loadVideos(channel, 1);

    setBusy("channels");
    setError(null);
    setChannels(null);
    setChannel(null);
    setPage(null);
    setSelected(null);
    try {
      const r = await api.channels(youtuber.trim());
      setChannelQuery(youtuber.trim());
      setChannels(r.channels);
      setBusy(null);
      if (r.channels.length === 1) await chooseChannel(r.channels[0]);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  async function uploadFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      const r = await api.upload(file);
      setDirect(r.path);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function start() {
    const source = mode === "search" ? selected?.url : direct.trim();
    if (!source) return;
    setError(null);
    setResult(null);
    try {
      const j = await api.startJob({
        source,
        min_clips: minClips,
        max_clips: Math.max(minClips, maxClips),
        min_len: minLen,
        max_len: Math.max(minLen, maxLen),
        format,
        fresh,
        keep_source: keepSource,
      });
      setJob(j);
      setTimeout(() => progressRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const running = job?.status === "running";
  const source = mode === "search" ? selected?.url : direct.trim();
  const matched = page?.videos.filter((v) => v.matched) ?? [];
  const unmatched = page?.videos.filter((v) => !v.matched) ?? [];
  const rangeLabel = page ? `${page.start}–${page.start + page.count - 1}` : "";
  const searchLabel = channel && channelQuery === youtuber.trim() ? "Check videos" : "Search";

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_1fr]">
      {/* ------------------------------------------------------------ left */}
      <div className="space-y-4 lg:sticky lg:top-20 lg:h-fit">
        <Card title="Source">
          <Segmented<Mode>
            value={mode}
            onChange={setMode}
            disabled={running}
            options={[
              { value: "search", label: "Search YouTuber" },
              { value: "direct", label: "Link or file" },
            ]}
          />

          {mode === "search" ? (
            <form
              className="mt-4 space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                search();
              }}
            >
              <Field label="YouTuber" hint="Name, @handle or channel link">
                <Input ref={youtuberRef} value={youtuber} onChange={(e) => setYoutuber(e.target.value)} placeholder="Ali Abdaal" />
              </Field>
              <Field label="Topic">
                <Input ref={topicRef} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="productivity" />
              </Field>
              <Field label="Videos to check per page">
                <NumberInput min={1} max={25} value={count} onChange={setCount} />
              </Field>
              <Button type="submit" className="w-full" loading={busy !== null} disabled={running}>
                {searchLabel}
              </Button>
            </form>
          ) : (
            <div className="mt-4 space-y-3">
              <Field label="YouTube link or file path">
                <Input
                  value={direct}
                  onChange={(e) => setDirect(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=…"
                />
              </Field>
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-zinc-100" />
                <span className="text-[11px] text-zinc-400">or</span>
                <div className="h-px flex-1 bg-zinc-100" />
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="video/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && uploadFile(e.target.files[0])}
              />
              <Button type="button" className="w-full" loading={uploading} disabled={running} onClick={() => fileRef.current?.click()}>
                Upload a video file
              </Button>
            </div>
          )}
        </Card>

        <Card title="Clip settings">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Min clips">
              <NumberInput min={1} max={20} value={minClips} onChange={setMinClips} />
            </Field>
            <Field label="Max clips">
              <NumberInput min={1} max={20} value={maxClips} onChange={setMaxClips} />
            </Field>
            <Field label="Min length (sec)">
              <NumberInput min={5} max={600} value={minLen} onChange={setMinLen} />
            </Field>
            <Field label="Max length (sec)">
              <NumberInput min={5} max={600} value={maxLen} onChange={setMaxLen} />
            </Field>
          </div>
          <div className="mt-4 rounded-md border border-zinc-200 p-3">
            <label className={cx("flex items-start gap-2.5", hasBackgrounds ? "cursor-pointer" : "cursor-not-allowed")}>
              <input
                type="checkbox"
                checked={useBackground && hasBackgrounds}
                disabled={!hasBackgrounds}
                onChange={(e) => setUseBackground(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-zinc-300 accent-zinc-900"
              />
              <span>
                <span className="block text-sm text-zinc-900">Add a background video</span>
                <span className="block text-xs text-zinc-500">
                  {hasBackgrounds
                    ? `Each clip gets a random one of your ${backgroundCount} backgrounds, cut to the clip's length.`
                    : "No backgrounds yet. Add some on the Backgrounds page."}
                </span>
              </span>
            </label>
            {useBackground && hasBackgrounds && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                <LayoutOption value="background" selected={layout === "background"} onSelect={() => setLayout("background")} />
                <LayoutOption value="split" selected={layout === "split"} onSelect={() => setLayout("split")} />
              </div>
            )}
          </div>
          {!(useBackground && hasBackgrounds) && (
            <div className="mt-4">
              <span className="mb-1.5 block text-xs font-medium text-zinc-700">Format</span>
              <Segmented<PlainFormat>
                value={plainFormat}
                onChange={setPlainFormat}
                options={[
                  { value: "crop", label: "Crop 9:16" },
                  { value: "blur", label: "Blur 9:16" },
                  { value: "original", label: "Original" },
                ]}
              />
            </div>
          )}
          <p className="mt-1.5 text-xs text-zinc-500">{FORMAT_HINT[format]}</p>
          <label className="mt-4 flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={fresh}
              onChange={(e) => setFresh(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-zinc-300 accent-zinc-900"
            />
            <span>
              <span className="block text-sm text-zinc-900">Pick new clips</span>
              <span className="block text-xs text-zinc-500">Ignore saved clip picks if this video was processed before.</span>
            </span>
          </label>
          <label className="mt-3 flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={keepSource}
              onChange={(e) => setKeepSource(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-zinc-300 accent-zinc-900"
            />
            <span>
              <span className="block text-sm text-zinc-900">Keep source video</span>
              <span className="block text-xs text-zinc-500">
                Deleted after clipping by default. The transcript is always kept, so new clips only need a re-download.
              </span>
            </span>
          </label>
        </Card>

        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">Selected video</p>
          <p className={cx("mt-1 line-clamp-2 text-sm", source ? "text-zinc-900" : "text-zinc-400")}>
            {mode === "search" ? selected?.title ?? "Choose a video from the results" : direct.trim() || "Enter a link or upload a file"}
          </p>
          <Button variant="primary" className="mt-3 w-full" disabled={!source || running} onClick={start}>
            {running ? "Processing…" : "Generate clips"}
          </Button>
        </div>
      </div>

      {/* ----------------------------------------------------------- right */}
      <div className="min-w-0 space-y-6">
        {error && <Alert>{error}</Alert>}

        {job && (
          <div ref={progressRef} className="scroll-mt-20 space-y-6">
            <JobProgress job={job} title={job.result?.title ?? (running ? "Generating clips" : "Last job")} />
            {result && (
              <div>
                <div className="mb-3 flex items-end justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-zinc-900">Clips</h2>
                    <p className="text-xs text-zinc-500">
                      {result.clips.length} clips saved to data/clips/
                    </p>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => onOpenLibrary(result.slug)}>
                    Open in library
                  </Button>
                </div>
                <ClipList clips={result.clips} />
              </div>
            )}
          </div>
        )}

        {mode === "search" && (
          <>
            {busy === "channels" && (
              <Card title="Channels">
                <div className="flex items-center gap-2 text-sm text-zinc-500">
                  <Spinner /> Searching YouTube
                </div>
              </Card>
            )}

            {channels && (
              <Card
                title="Channels"
                description={channels.length ? "Pick the right channel." : undefined}
              >
                {channels.length === 0 ? (
                  <p className="text-sm text-zinc-500">No channels found for “{channelQuery}”.</p>
                ) : (
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {channels.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        disabled={busy !== null || running}
                        onClick={() => chooseChannel(c)}
                        className={cx(
                          "flex items-center justify-between rounded-md border px-3 py-2.5 text-left transition-colors disabled:cursor-not-allowed",
                          channel?.id === c.id
                            ? "border-zinc-900 bg-zinc-50 ring-1 ring-zinc-900"
                            : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
                        )}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-zinc-900">{c.name}</span>
                          <span className="block truncate text-xs text-zinc-500">{c.handle}</span>
                        </span>
                        <span className="ml-3 shrink-0 text-xs text-zinc-500">{formatCount(c.subscribers, "subs")}</span>
                      </button>
                    ))}
                  </div>
                )}
              </Card>
            )}

            {channel && (
              <Card
                title={`Videos ${rangeLabel}`}
                description={
                  page && !page.end_of_channel
                    ? `${channel.name} · ${matched.length} of ${page.videos.length} about “${checkedTopic}”`
                    : channel.name
                }
                actions={
                  <>
                    <Button
                      size="sm"
                      disabled={!page || page.start <= 1 || busy !== null}
                      onClick={() => loadVideos(channel, Math.max(1, page!.start - count))}
                    >
                      Newer
                    </Button>
                    <Button
                      size="sm"
                      disabled={!page || page.end_of_channel || busy !== null}
                      onClick={() => loadVideos(channel, page!.start + page!.count)}
                    >
                      Older
                    </Button>
                  </>
                }
              >
                {busy === "videos" ? (
                  <div className="flex items-center gap-2 text-sm text-zinc-500">
                    <Spinner /> Loading videos and checking the topic. This can take up to a minute.
                  </div>
                ) : !page ? null : page.end_of_channel ? (
                  <EmptyState title="No more videos">This channel has no older videos.</EmptyState>
                ) : (
                  <div className="space-y-4">
                    {matched.length === 0 && (
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 px-4 py-4">
                        <p className="text-sm font-medium text-zinc-900">
                          No videos about “{checkedTopic}” in videos {rangeLabel}.
                        </p>
                        <p className="mt-0.5 text-xs text-zinc-500">What would you like to do?</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            onClick={() => {
                              setChannels(null);
                              setChannel(null);
                              setPage(null);
                              setChannelQuery(null);
                              setYoutuber("");
                              youtuberRef.current?.focus();
                            }}
                          >
                            Switch YouTuber
                          </Button>
                          <Button
                            size="sm"
                            onClick={() => {
                              topicRef.current?.focus();
                              topicRef.current?.select();
                            }}
                          >
                            Change topic
                          </Button>
                          <Button size="sm" variant="primary" onClick={() => loadVideos(channel, page.start + page.count)}>
                            Inspect older videos
                          </Button>
                        </div>
                      </div>
                    )}

                    {matched.length > 0 && (
                      <ul className="space-y-2">
                        {matched.map((v) => (
                          <VideoRow key={v.id} video={v} selected={selected?.id === v.id} onSelect={() => setSelected(v)} />
                        ))}
                      </ul>
                    )}

                    {unmatched.length > 0 && (
                      <div>
                        <button
                          type="button"
                          onClick={() => setShowUnmatched((s) => !s)}
                          className="text-xs font-medium text-zinc-500 hover:text-zinc-900"
                        >
                          {showUnmatched ? "Hide" : "Show"} {unmatched.length} other video{unmatched.length === 1 ? "" : "s"}
                        </button>
                        {showUnmatched && (
                          <ul className="mt-2 space-y-2">
                            {unmatched.map((v) => (
                              <VideoRow key={v.id} video={v} selected={selected?.id === v.id} onSelect={() => setSelected(v)} />
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </Card>
            )}

            {!channels && busy === null && !job && (
              <EmptyState title="Find a video to clip">
                Enter a YouTuber and a topic. Their latest videos are checked against the topic.
              </EmptyState>
            )}
          </>
        )}

        {mode === "direct" && !job && (
          <EmptyState title="Clip a specific video">
            Paste a YouTube link or a file path, or upload a file, then generate clips.
          </EmptyState>
        )}
      </div>
    </div>
  );
}

function VideoRow({ video, selected, onSelect }: { video: Video; selected: boolean; onSelect: () => void }) {
  const desc = video.description
    .split("\n")
    .filter((l) => !l.includes("http"))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={cx(
          "flex w-full gap-4 rounded-md border p-3 text-left transition-colors",
          selected ? "border-zinc-900 ring-1 ring-zinc-900" : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
          !video.matched && !selected && "opacity-70",
        )}
      >
        <div className="relative shrink-0">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={video.thumbnail} alt="" className="h-[72px] w-32 rounded object-cover sm:h-[90px] sm:w-40" />
          <span className="absolute right-1 bottom-1 rounded bg-black/75 px-1 py-px font-mono text-[10px] text-white">
            {formatDuration(video.duration)}
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <p className="line-clamp-2 text-sm font-medium leading-snug text-zinc-900">{video.title}</p>
            <span
              className={cx(
                "mt-0.5 h-4 w-4 shrink-0 rounded-full border",
                selected ? "border-[5px] border-zinc-900" : "border-zinc-300",
              )}
              aria-hidden
            />
          </div>
          <p className="mt-0.5 text-xs text-zinc-500">
            {formatDate(video.upload_date)}
            {video.view_count ? ` · ${formatCount(video.view_count, "views")}` : ""}
          </p>
          {desc && <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-zinc-500">{desc}</p>}
          <div className="mt-1.5 flex items-start gap-2">
            {video.matched ? <Badge tone="success">Matches</Badge> : <Badge>No match</Badge>}
            {video.reason && <span className="text-xs text-zinc-600">{video.reason}</span>}
          </div>
        </div>
      </button>
    </li>
  );
}
