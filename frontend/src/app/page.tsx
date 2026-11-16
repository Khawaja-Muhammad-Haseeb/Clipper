"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { api, type Config } from "@/lib/api";
import { Library } from "@/components/Library";
import { NewJob } from "@/components/NewJob";
import { cx } from "@/components/ui";

type View = "new" | "library";

const subscribeHash = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};

function shortModel(m: string) {
  return m.split("/").pop()?.replace(/:free$/, "") ?? m;
}

export default function Home() {
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash, () => "");
  const view: View = hash === "#library" ? "library" : "new";
  const setView = (v: View) => {
    window.location.assign(v === "library" ? "#library" : "#");
  };
  const [librarySlug, setLibrarySlug] = useState<string | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setOffline(true));
  }, []);

  const missing = config && [!config.llm_key_set && "LLM_API_KEY", config.transcribe === "groq" && !config.groq_key_set && "GROQ_API_KEY", !config.llm_models.length && "LLM_MODEL"].filter(Boolean);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-8 px-4 sm:px-6">
          <div className="flex items-center gap-2">
            <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden>
              <rect x="1" y="1" width="18" height="18" rx="4" fill="#18181b" />
              <path d="M8 6.5v7l5.5-3.5z" fill="#fff" />
            </svg>
            <span className="text-sm font-semibold tracking-tight">Clipper</span>
          </div>
          <nav className="flex h-full gap-6">
            {(
              [
                ["new", "New job"],
                ["library", "Library"],
              ] as [View, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setView(key)}
                className={cx(
                  "-mb-px border-b-2 text-sm transition-colors",
                  view === key ? "border-zinc-900 font-medium text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-900",
                )}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-4 text-xs text-zinc-500 md:flex">
            {offline ? (
              <span className="flex items-center gap-1.5 text-red-600">
                <span className="h-1.5 w-1.5 rounded-full bg-red-600" /> Server offline
              </span>
            ) : config ? (
              <>
                <span>
                  Whisper: <span className="text-zinc-700">{config.transcribe === "groq" ? "Groq" : "Local"}</span>
                </span>
                <span className="max-w-[260px] truncate">
                  Model: <span className="text-zinc-700">{config.llm_models[0] ? shortModel(config.llm_models[0]) : "not set"}</span>
                  {config.llm_models.length > 1 && ` +${config.llm_models.length - 1} fallback`}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" /> Connected
                </span>
              </>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
        {missing && missing.length > 0 && (
          <div className="mb-6 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Missing in .env: {missing.join(", ")}. Add them and restart the server.
          </div>
        )}
        {offline && (
          <div className="mb-6 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            Cannot reach the Clipper server. Start it with <code className="font-mono">.venv\Scripts\clipper-server</code>.
          </div>
        )}
        <div className={view === "new" ? "" : "hidden"}>
          <NewJob
            onOpenLibrary={(slug) => {
              setLibrarySlug(slug);
              setView("library");
            }}
          />
        </div>
        {view === "library" && <Library key={librarySlug ?? "lib"} initialSlug={librarySlug} />}
      </main>
    </div>
  );
}
