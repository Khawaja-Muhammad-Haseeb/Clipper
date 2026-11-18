export const API = process.env.NEXT_PUBLIC_API_URL ?? "";

export type Config = {
  llm_models: string[];
  llm_base_url: string;
  llm_key_set: boolean;
  transcribe: string;
  groq_key_set: boolean;
  background_count: number;
};

export type Channel = {
  name: string;
  handle: string | null;
  id: string;
  url: string;
  subscribers: number | null;
};

export type Video = {
  id: string;
  url: string;
  title: string;
  description: string;
  upload_date: string | null;
  duration: number | null;
  view_count: number | null;
  thumbnail: string;
  matched: boolean;
  reason: string;
};

export type VideoPage = {
  videos: Video[];
  start: number;
  count: number;
  end_of_channel: boolean;
};

export type ClipFormat = "crop" | "blur" | "original" | "background" | "split";

export type Background = {
  id: string;
  file: string;
  thumb: string | null;
  title: string;
  channel: string | null;
  url: string | null;
  duration: number | null;
  added: string | null;
  size_mb: number;
};

export type BackgroundTask = {
  running: boolean;
  done: number;
  total: number;
  current: string | null;
  error: string | null;
  added: number;
};

export type JobRequest = {
  source: string;
  min_clips: number;
  max_clips: number;
  min_len: number;
  max_len: number;
  format: ClipFormat;
  fresh: boolean;
  keep_source: boolean;
  end_screen: boolean;
};

export type Stage = {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "error";
  progress: number;
  detail: string | null;
  indeterminate: boolean;
};

export type Job = {
  id: string;
  status: "running" | "done" | "error";
  error: string | null;
  result: { slug: string; title: string; clips: string[] } | null;
  request: JobRequest;
  started: number;
  finished: number | null;
  overall: number;
  stages: Stage[];
  logs: string[];
};

export type SourceVideo = {
  id?: string;
  title?: string;
  channel?: string | null;
  url?: string | null;
  source?: string | null;
};

export type Clip = {
  name: string;
  clip_number: number;
  working_title: string;
  summary: string;
  hook: string;
  reason: string;
  transcript: string;
  start: string;
  end: string;
  duration_sec: number;
  format: string;
  background?: { id: string; start_sec: number } | null;
  end_screens?: { instagram?: string; youtube?: string } | null;
  created_at: string;
  source_video: SourceVideo;
  video: string | null;
  json: string;
  instagram: {
    caption: string;
    hashtags: string[];
    full_caption: string;
    uploaded: boolean;
  } | null;
  youtube: {
    title: string;
    description: string;
    tags: string[];
    hashtags: string[];
    full_description: string;
    uploaded: boolean;
  } | null;
};

export type LibraryItem = {
  slug: string;
  title: string;
  channel: string | null;
  url: string | null;
  clip_count: number;
  updated: number;
  thumbnail: string | null;
};

export type LibraryDetail = {
  slug: string;
  title: string;
  source_video: SourceVideo;
  can_reclip: boolean;
  clips: Clip[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, init);
  } catch {
    throw new Error("Cannot reach the Clipper server. Is clipper-server running?");
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const api = {
  config: () => request<Config>("/api/config"),
  channels: (query: string) => post<{ channels: Channel[] }>("/api/channels", { query }),
  videos: (channel: Channel, topic: string, start: number, count: number) =>
    post<VideoPage>("/api/videos", { channel, topic, start, count }),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ path: string }>("/api/upload", { method: "POST", body: fd });
  },
  startJob: (req: JobRequest) => post<Job>("/api/jobs", req),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  currentJob: () => request<Job | null>("/api/jobs/current"),
  library: () => request<{ items: LibraryItem[] }>("/api/library"),
  libraryItem: (slug: string) => request<LibraryDetail>(`/api/library/${encodeURIComponent(slug)}`),
  backgrounds: () => request<{ items: Background[]; task: BackgroundTask }>("/api/backgrounds"),
  backgroundStatus: () => request<BackgroundTask>("/api/backgrounds/status"),
  downloadBackgrounds: (count: number) => post<BackgroundTask>("/api/backgrounds/download", { count }),
  addBackgroundLink: (url: string) => post<BackgroundTask>("/api/backgrounds/youtube", { url }),
  uploadBackground: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ id: string }>("/api/backgrounds/upload", { method: "POST", body: fd });
  },
  deleteBackground: (id: string) => request<{ ok: boolean }>(`/api/backgrounds/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

export const mediaUrl = (path: string | null | undefined) => (path ? `${API}${path}` : "");

/** The clip joined with a platform's end screen ("none" = bare clip). */
export const clipDownloadUrl = (slug: string, name: string, platform: "instagram" | "youtube" | "none") =>
  `${API}/api/library/${encodeURIComponent(slug)}/${encodeURIComponent(name)}/download?platform=${platform}`;

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return "–";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

export function formatDate(d: string | null | undefined): string {
  if (!d || d.length !== 8) return "Unknown date";
  const date = new Date(`${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}T00:00:00`);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatCount(n: number | null | undefined, unit: string): string {
  if (!n) return `– ${unit}`;
  const fmt = (v: number, s: string) => `${v.toFixed(1).replace(/\.0$/, "")}${s} ${unit}`;
  if (n >= 1e9) return fmt(n / 1e9, "B");
  if (n >= 1e6) return fmt(n / 1e6, "M");
  if (n >= 1e3) return fmt(n / 1e3, "K");
  return `${n} ${unit}`;
}
