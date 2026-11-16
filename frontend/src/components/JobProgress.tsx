"use client";

import { useEffect, useRef, useState } from "react";
import type { Job, Stage } from "@/lib/api";
import { Card, ProgressBar, Spinner, cx } from "./ui";

function StageIcon({ status }: { status: Stage["status"] }) {
  if (status === "running") return <Spinner className="text-zinc-900" />;
  return (
    <span
      className={cx(
        "flex h-3.5 w-3.5 items-center justify-center rounded-full",
        status === "done" && "bg-emerald-600",
        status === "error" && "bg-red-600",
        status === "pending" && "border border-zinc-300 bg-white",
      )}
    >
      {status === "done" && (
        <svg viewBox="0 0 12 12" className="h-2.5 w-2.5 text-white" fill="none" aria-hidden>
          <path d="M2.5 6.2 5 8.5l4.5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {status === "error" && <span className="text-[9px] font-bold leading-none text-white">!</span>}
    </span>
  );
}

function useElapsed(job: Job) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (job.status !== "running") return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [job.status]);
  const end = job.finished ?? now;
  const s = Math.max(0, Math.round(end - job.started));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function JobProgress({ job, title }: { job: Job; title?: string }) {
  const [showLog, setShowLog] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);
  const elapsed = useElapsed(job);

  useEffect(() => {
    if (showLog && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [job.logs.length, showLog]);

  const statusText =
    job.status === "running" ? "Processing" : job.status === "done" ? "Completed" : "Failed";

  return (
    <Card
      title={title ?? "Progress"}
      description={job.request.source}
      actions={
        <span className="font-mono text-xs text-zinc-500">
          {statusText} · {elapsed}
        </span>
      }
    >
      <div className="mb-5">
        <div className="mb-1.5 flex justify-between text-xs">
          <span className="font-medium text-zinc-700">Overall</span>
          <span className="font-mono text-zinc-500">{Math.round(job.overall * 100)}%</span>
        </div>
        <ProgressBar
          value={job.overall}
          tone={job.status === "done" ? "success" : job.status === "error" ? "danger" : "default"}
          className="h-2"
        />
      </div>

      <ol className="space-y-3.5">
        {job.stages.map((s) => (
          <li key={s.key} className="grid grid-cols-[14px_1fr] gap-x-3">
            <div className="pt-0.5">
              <StageIcon status={s.status} />
            </div>
            <div>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className={cx(s.status === "pending" ? "text-zinc-400" : "text-zinc-900")}>{s.label}</span>
                <span className="truncate font-mono text-xs text-zinc-500">
                  {s.detail ?? (s.status === "done" ? "Done" : s.status === "pending" ? "" : `${Math.round(s.progress * 100)}%`)}
                </span>
              </div>
              {s.status !== "pending" && (
                <ProgressBar
                  className="mt-1.5"
                  value={s.status === "done" ? 1 : s.progress}
                  indeterminate={s.status === "running" && s.indeterminate}
                  tone={s.status === "error" ? "danger" : s.status === "done" ? "success" : "default"}
                />
              )}
            </div>
          </li>
        ))}
      </ol>

      {job.error && (
        <div className="mt-5 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{job.error}</div>
      )}

      <div className="mt-5 border-t border-zinc-100 pt-3">
        <button
          type="button"
          onClick={() => setShowLog((v) => !v)}
          className="text-xs font-medium text-zinc-500 hover:text-zinc-900"
        >
          {showLog ? "Hide log" : "Show log"} ({job.logs.length})
        </button>
        {showLog && (
          <pre
            ref={logRef}
            className="mt-2 max-h-64 overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-zinc-300"
          >
            {job.logs.join("\n") || "No output yet."}
          </pre>
        )}
      </div>
    </Card>
  );
}
