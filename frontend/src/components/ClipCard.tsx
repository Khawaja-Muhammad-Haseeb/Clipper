"use client";

import { useState } from "react";
import { type Clip, clipDownloadUrl, formatDuration, mediaUrl } from "@/lib/api";
import { Badge, CopyButton, cx } from "./ui";

type Tab = "instagram" | "youtube" | "details";

function Block({ label, copy, children }: { label: string; copy?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">{label}</span>
        {copy && <CopyButton text={copy} />}
      </div>
      {children}
    </div>
  );
}

function Chips({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((t) => (
        <span key={t} className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-700">
          {t}
        </span>
      ))}
    </div>
  );
}

export function ClipCard({ slug, clip }: { slug: string; clip: Clip }) {
  const [tab, setTab] = useState<Tab>("instagram");
  // The player plays the clip, then the end screen of the platform tab that's open.
  const [phase, setPhase] = useState<"clip" | "end">("clip");
  const video = clip.video;
  const vertical = clip.format !== "original";
  const title = clip.youtube?.title || clip.working_title;
  const platform = tab === "youtube" ? "youtube" : "instagram";
  const endScreen = clip.end_screens?.[platform];
  const src = phase === "end" && endScreen ? mediaUrl(endScreen) : `${mediaUrl(video)}#t=0.1`;

  return (
    <article className="flex flex-col overflow-hidden rounded-lg border border-zinc-200 bg-white sm:flex-row">
      <div className={cx("shrink-0 bg-zinc-950", vertical ? "sm:w-[220px]" : "sm:w-[320px]")}>
        {video ? (
          <div className="relative">
            <video
              key={src}
              src={src}
              controls
              autoPlay={phase === "end"}
              preload="metadata"
              onEnded={() => setPhase(phase === "clip" && endScreen ? "end" : "clip")}
              className={cx("mx-auto h-full w-full object-contain", vertical ? "aspect-[9/16] max-h-[420px]" : "aspect-video")}
            />
            {phase === "end" && (
              <span className="pointer-events-none absolute top-2 left-2 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
                End screen · {platform === "youtube" ? "YouTube" : "Instagram"}
              </span>
            )}
          </div>
        ) : (
          <div className="flex aspect-[9/16] items-center justify-center text-xs text-zinc-500">Video missing</div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-zinc-100 px-4 pt-3.5 pb-3">
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span className="font-mono">#{String(clip.clip_number).padStart(2, "0")}</span>
            <span>·</span>
            <span className="font-mono">
              {clip.start}–{clip.end}
            </span>
            <span>·</span>
            <span>{formatDuration(clip.duration_sec)}</span>
            <Badge>{clip.format}</Badge>
          </div>
          <h3 className="mt-1 text-sm font-semibold leading-snug text-zinc-900">{title}</h3>
          {clip.summary && <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">{clip.summary}</p>}
        </div>

        <div className="flex gap-4 border-b border-zinc-100 px-4">
          {(
            [
              ["instagram", "Instagram"],
              ["youtube", "YouTube"],
              ["details", "Transcript"],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={cx(
                "-mb-px border-b-2 py-2 text-xs font-medium transition-colors",
                tab === key ? "border-zinc-900 text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-900",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3.5 sm:max-h-[330px]">
          {tab === "instagram" &&
            (clip.instagram ? (
              <>
                <Block label="Caption" copy={clip.instagram.caption}>
                  <p className="whitespace-pre-line text-sm leading-relaxed text-zinc-800">{clip.instagram.caption}</p>
                </Block>
                <Block label={`Hashtags (${clip.instagram.hashtags.length})`} copy={clip.instagram.hashtags.join(" ")}>
                  <Chips items={clip.instagram.hashtags} />
                </Block>
              </>
            ) : (
              <p className="text-sm text-zinc-500">No Instagram metadata.</p>
            ))}

          {tab === "youtube" &&
            (clip.youtube ? (
              <>
                <Block label="Title" copy={clip.youtube.title}>
                  <p className="text-sm text-zinc-800">{clip.youtube.title}</p>
                </Block>
                <Block label="Description" copy={clip.youtube.full_description || clip.youtube.description}>
                  <p className="whitespace-pre-line text-sm leading-relaxed text-zinc-800">{clip.youtube.description}</p>
                </Block>
                <Block label="Hashtags" copy={clip.youtube.hashtags.join(" ")}>
                  <Chips items={clip.youtube.hashtags} />
                </Block>
                <Block label={`Tags (${clip.youtube.tags.length})`} copy={clip.youtube.tags.join(", ")}>
                  <Chips items={clip.youtube.tags} />
                </Block>
              </>
            ) : (
              <p className="text-sm text-zinc-500">No YouTube metadata.</p>
            ))}

          {tab === "details" && (
            <>
              {clip.hook && (
                <Block label="Hook">
                  <p className="text-sm text-zinc-800">{clip.hook}</p>
                </Block>
              )}
              {clip.reason && (
                <Block label="Why this clip">
                  <p className="text-sm text-zinc-800">{clip.reason}</p>
                </Block>
              )}
              <Block label="Transcript" copy={clip.transcript}>
                <p className="text-sm leading-relaxed text-zinc-700">{clip.transcript || "No transcript."}</p>
              </Block>
            </>
          )}
        </div>

        <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-zinc-100 px-4 py-2.5 text-xs">
          {clip.video && clip.end_screens ? (
            <>
              <a className="font-medium text-zinc-700 hover:text-zinc-900 hover:underline" href={clipDownloadUrl(slug, clip.name, "instagram")}>
                Download for Instagram
              </a>
              <a className="font-medium text-zinc-700 hover:text-zinc-900 hover:underline" href={clipDownloadUrl(slug, clip.name, "youtube")}>
                Download for YouTube
              </a>
              <a className="text-zinc-500 hover:text-zinc-900 hover:underline" href={mediaUrl(clip.video)} download>
                Without end screen
              </a>
            </>
          ) : (
            clip.video && (
              <a className="font-medium text-zinc-700 hover:text-zinc-900 hover:underline" href={mediaUrl(clip.video)} download>
                Download video
              </a>
            )
          )}
          <a className="text-zinc-500 hover:text-zinc-900 hover:underline" href={mediaUrl(clip.json)} target="_blank" rel="noreferrer">
            JSON
          </a>
          <span className="ml-auto truncate font-mono text-[11px] text-zinc-400">{clip.name}</span>
        </footer>
      </div>
    </article>
  );
}

export function ClipList({ slug, clips }: { slug: string; clips: Clip[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
      {clips.map((c) => (
        <ClipCard key={c.name} slug={slug} clip={c} />
      ))}
    </div>
  );
}
