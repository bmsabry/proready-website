/**
 * Shared admin UI primitives — the visual vocabulary every admin page speaks.
 * Extracted from the old single-file dashboard (Kpi, StatusBadge, LabeledInput)
 * and extended with the pieces the per-course workspaces need.
 */
import React from 'react';
import { RefreshCw } from 'lucide-react';

// ----- Notices ---------------------------------------------------------------

export function Notice({
  kind,
  children,
}: {
  kind: 'error' | 'success' | 'warn';
  children: React.ReactNode;
}) {
  const cls =
    kind === 'error'
      ? 'text-red-300 bg-red-950/40 border-red-900/60'
      : kind === 'success'
        ? 'text-emerald-200 bg-emerald-950/40 border-emerald-900/60'
        : 'text-amber-200 bg-amber-950/40 border-amber-900/60';
  return <div className={`mb-4 text-sm border rounded-lg px-3 py-2 ${cls}`}>{children}</div>;
}

// ----- KPI card --------------------------------------------------------------

export type KpiAccent = 'emerald' | 'amber' | 'slate' | 'cyan';

export function Kpi({
  icon,
  label,
  value,
  sub,
  accent = 'cyan',
}: {
  icon?: React.ReactNode;
  label: string;
  value: number | string;
  sub?: string;
  accent?: KpiAccent;
}) {
  const tone = {
    emerald: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
    amber: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
    slate: 'text-slate-300 bg-slate-500/10 border-slate-500/30',
    cyan: 'text-cyan-300 bg-cyan-500/10 border-cyan-500/30',
  }[accent];
  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-2 text-xs text-slate-300 uppercase tracking-wide">
        {icon && (
          <span className={`inline-flex items-center justify-center w-6 h-6 rounded-md border ${tone}`}>
            {icon}
          </span>
        )}
        {label}
      </div>
      <div className="text-2xl font-semibold text-white mt-2">{value}</div>
      {sub && <div className="text-[11px] text-slate-400 mt-1">{sub}</div>}
    </div>
  );
}

// ----- Badges ----------------------------------------------------------------

/** Registration / course / product / software status pill. */
export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'bg-amber-500/20 text-amber-200 border-amber-500/40',
    paid: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
    cancelled: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
    open: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
    closed: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
    live: 'bg-cyan-500/20 text-cyan-200 border-cyan-500/40',
    draft: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
    hidden: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
    active: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
  };
  const cls = map[status] ?? 'bg-slate-700/30 text-slate-300 border-slate-600/40';
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${cls}`}>
      {status}
    </span>
  );
}

/** How a registration was paid: paypal / stripe / blank = manual invoice. */
export function ProviderBadge({ provider }: { provider?: string }) {
  const p = (provider ?? '').toLowerCase();
  if (p === 'paypal') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] border bg-sky-500/15 text-sky-300 border-sky-500/40">
        paypal
      </span>
    );
  }
  if (p === 'stripe') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] border bg-violet-500/15 text-violet-300 border-violet-500/40">
        stripe
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] border bg-slate-700/30 text-slate-300 border-slate-600/40">
      invoice
    </span>
  );
}

// ----- Form fields -----------------------------------------------------------

export function LabeledInput({
  label,
  value,
  onChange,
  type = 'text',
  min,
  step,
  icon,
  placeholder,
  required,
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  min?: number;
  step?: number | string;
  icon?: React.ReactNode;
  placeholder?: string;
  required?: boolean;
  mono?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider text-slate-300 flex items-center gap-1 mb-1">
        {icon}
        {label}
      </span>
      <input
        type={type}
        min={min}
        step={step}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 ${mono ? 'font-mono' : ''}`}
      />
    </label>
  );
}

export function LabeledSelect({
  label,
  value,
  onChange,
  children,
  icon,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
  icon?: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider text-slate-300 flex items-center gap-1 mb-1">
        {icon}
        {label}
      </span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 disabled:opacity-50"
      >
        {children}
      </select>
    </label>
  );
}

/** Subject + body pair shared by every broadcast composer. Plain text by
 * default (converted to HTML before sending), raw-HTML toggle for power use. */
export function MessageEditor({
  subject,
  onSubject,
  body,
  onBody,
  rawHtml,
  onRawHtml,
}: {
  subject: string;
  onSubject: (v: string) => void;
  body: string;
  onBody: (v: string) => void;
  rawHtml: boolean;
  onRawHtml: (v: boolean) => void;
}) {
  return (
    <>
      <LabeledInput label="Subject" value={subject} onChange={onSubject} />
      <label className="block">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[11px] uppercase tracking-wider text-slate-300">Message</span>
          <label className="flex items-center gap-2 text-[11px] text-slate-300 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={rawHtml}
              onChange={(e) => onRawHtml(e.target.checked)}
              className="accent-cyan-500"
            />
            Send as raw HTML
          </label>
        </div>
        <textarea
          value={body}
          onChange={(e) => onBody(e.target.value)}
          rows={9}
          placeholder={
            rawHtml
              ? '<p>Hi everyone,</p><p>A quick update…</p>'
              : 'Hi everyone,\n\nA quick update: …\n\nBest,\nAdam'
          }
          className={`w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 ${rawHtml ? 'font-mono' : ''}`}
        />
        <span className="text-[11px] text-slate-400 mt-1 block">
          {rawHtml
            ? 'Raw HTML mode — paste full markup. You own the formatting.'
            : 'Just type normally. Blank lines become paragraphs, single line breaks become <br>, links auto-detect.'}
        </span>
      </label>
    </>
  );
}

// ----- Layout helpers --------------------------------------------------------

export function Section({
  icon,
  title,
  sub,
  actions,
  children,
  className = '',
}: {
  icon?: React.ReactNode;
  title: React.ReactNode;
  sub?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            {icon}
            {title}
          </h2>
          {sub && <p className="text-sm text-slate-300 mt-1 max-w-2xl">{sub}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  hint?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-10 text-center">
      {icon && (
        <div className="mx-auto mb-3 w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 flex items-center justify-center">
          {icon}
        </div>
      )}
      <div className="text-white font-semibold">{title}</div>
      {hint && <p className="text-sm text-slate-300 mt-2 max-w-md mx-auto">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

/** Button that runs its action only after a window.confirm(). */
export function ConfirmButton({
  message,
  onConfirm,
  className,
  disabled,
  title,
  children,
}: {
  message: string;
  onConfirm: () => void;
  className?: string;
  disabled?: boolean;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      className={className}
      onClick={() => {
        if (window.confirm(message)) onConfirm();
      }}
    >
      {children}
    </button>
  );
}

export function RefreshButton({
  onClick,
  loading,
  small,
}: {
  onClick: () => void;
  loading?: boolean;
  small?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`btn-secondary flex items-center gap-2 disabled:opacity-50 ${small ? 'text-xs py-1.5 px-2.5' : 'text-sm py-2 px-3'}`}
    >
      <RefreshCw className={`${small ? 'w-3 h-3' : 'w-4 h-4'} ${loading ? 'animate-spin' : ''}`} />
      Refresh
    </button>
  );
}

// ----- Tiny charts (pure CSS — no chart lib) ---------------------------------

/** Vertical bar strip; each bar gets a hover tooltip via title. */
export function BarChart({
  data,
  height = 112,
}: {
  data: { label: string; count: number }[];
  height?: number;
}) {
  const max = data.reduce((m, d) => Math.max(m, d.count), 0) || 1;
  return (
    <div className="flex items-end gap-px" style={{ height }}>
      {data.map((d) => (
        <div
          key={d.label}
          className="flex-1 min-w-0 flex flex-col justify-end h-full"
          title={`${d.label}: ${d.count}`}
        >
          {d.count > 0 ? (
            <div
              className="w-full rounded-t bg-cyan-500/70"
              style={{ height: `${Math.max(5, (d.count / max) * 100)}%` }}
            />
          ) : (
            <div className="w-full bg-slate-800" style={{ height: 2 }} />
          )}
        </div>
      ))}
    </div>
  );
}

/** Horizontal label + proportional bar list (companies, features, versions). */
export function HBarList({
  rows,
  empty,
}: {
  rows: { label: string; count: number }[];
  empty: string;
}) {
  const max = rows.reduce((m, r) => Math.max(m, r.count), 0) || 1;
  if (rows.length === 0) return <p className="text-sm text-slate-400">{empty}</p>;
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.label} className="text-sm">
          <div className="flex items-center justify-between mb-1 gap-4">
            <span className="text-slate-300 truncate">{r.label}</span>
            <span className="text-slate-400 shrink-0">{r.count.toLocaleString()}</span>
          </div>
          <div className="h-1.5 rounded bg-slate-800">
            <div
              className="h-1.5 rounded bg-cyan-500/70"
              style={{ width: `${Math.max(4, (r.count / max) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Seat occupancy: emerald = paid, amber = pending, dark = free. */
export function SeatsBar({
  paid,
  taken,
  total,
}: {
  paid: number;
  taken: number;
  total: number;
}) {
  const pct = (n: number) => (total > 0 ? Math.min(100, Math.max(0, (n / total) * 100)) : 0);
  return (
    <div
      className="h-2 rounded-full bg-slate-800 overflow-hidden flex"
      title={`${paid} paid · ${Math.max(0, taken - paid)} pending · ${Math.max(0, total - taken)} free of ${total}`}
    >
      <div className="bg-emerald-500/80 h-full" style={{ width: `${pct(paid)}%` }} />
      <div className="bg-amber-500/70 h-full" style={{ width: `${pct(Math.max(0, taken - paid))}%` }} />
    </div>
  );
}
