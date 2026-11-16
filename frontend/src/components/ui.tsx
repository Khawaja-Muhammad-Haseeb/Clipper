"use client";

import { useState, type ButtonHTMLAttributes, type ComponentProps, type ReactNode } from "react";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 focus-visible:ring-offset-1",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm",
        variant === "primary" && "bg-zinc-900 text-white hover:bg-zinc-800",
        variant === "secondary" && "border border-zinc-200 bg-white text-zinc-900 hover:bg-zinc-50",
        variant === "ghost" && "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
        className,
      )}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("h-3.5 w-3.5 animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Input({ className, ...rest }: ComponentProps<"input">) {
  return (
    <input
      {...rest}
      className={cx(
        "h-9 w-full rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 placeholder:text-zinc-400",
        "focus:border-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-200",
        "disabled:bg-zinc-50 disabled:text-zinc-500",
        className,
      )}
    />
  );
}

/**
 * Number field you can freely clear and retype. While typing, the text is kept as-is and
 * every valid number is passed up (clamped to min..max). On blur the field snaps to the
 * clamped value, or back to the last valid one if it was left empty.
 */
export function NumberInput({ value, onChange, min, max, className }: {
  value: number;
  onChange: (n: number) => void;
  min: number;
  max: number;
  className?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const clamp = (n: number) => Math.max(min, Math.min(max, Math.round(n)));
  return (
    <Input
      type="text"
      inputMode="numeric"
      className={className}
      value={draft ?? String(value)}
      onChange={(e) => {
        const text = e.target.value.replace(/[^\d]/g, "");
        setDraft(text);
        if (text !== "") onChange(clamp(Number(text)));
      }}
      onBlur={() => setDraft(null)}
    />
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1.5 block text-xs font-medium text-zinc-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export function Card({ title, description, actions, children, className }: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-zinc-200 bg-white", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-zinc-100 px-5 py-3.5">
          <div>
            {title && <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Segmented<T extends string>({ value, options, onChange, disabled }: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex w-full rounded-md border border-zinc-200 bg-zinc-50 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cx(
            "flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed",
            value === o.value ? "bg-white text-zinc-900 shadow-sm ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-900",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "success" | "danger" | "info"; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium",
        tone === "neutral" && "bg-zinc-100 text-zinc-600",
        tone === "success" && "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
        tone === "danger" && "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200",
        tone === "info" && "bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200",
      )}
    >
      {children}
    </span>
  );
}

export function ProgressBar({ value, indeterminate, tone = "default", className }: {
  value: number;
  indeterminate?: boolean;
  tone?: "default" | "success" | "danger";
  className?: string;
}) {
  const color = tone === "success" ? "bg-emerald-600" : tone === "danger" ? "bg-red-600" : "bg-zinc-900";
  return (
    <div className={cx("relative h-1.5 w-full overflow-hidden rounded-full bg-zinc-100", className)}>
      {indeterminate ? (
        <div className={cx("animate-indeterminate absolute inset-y-0 w-2/5 rounded-full", color)} />
      ) : (
        <div className={cx("h-full rounded-full transition-[width] duration-500", color)} style={{ width: `${Math.round(value * 100)}%` }} />
      )}
    </div>
  );
}

export function Alert({ tone = "danger", children }: { tone?: "danger" | "info"; children: ReactNode }) {
  return (
    <div
      className={cx(
        "rounded-md border px-3 py-2 text-sm",
        tone === "danger" ? "border-red-200 bg-red-50 text-red-800" : "border-zinc-200 bg-zinc-50 text-zinc-700",
      )}
    >
      {children}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard blocked */
        }
      }}
      className="rounded px-1.5 py-0.5 text-[11px] font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900"
    >
      {copied ? "Copied" : label}
    </button>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-zinc-300 bg-white px-6 py-12 text-center">
      <p className="text-sm font-medium text-zinc-900">{title}</p>
      {children && <div className="mt-1 text-sm text-zinc-500">{children}</div>}
    </div>
  );
}
