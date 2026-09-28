/**
 * Sent emails: the rows of the log and the viewer that opens one.
 *
 * Used by Comms (the full log), Overview (latest emails) and each course's
 * Comms tab, so an email reads and opens the same way everywhere.
 *
 * The viewer shows the email as the recipient got it: the rendered HTML in a
 * sandboxed frame (no scripts can run, links open in a new tab), the plain
 * text part, every header, the attachments' names, and what became of it
 * after it left (delivered, bounced, opened…) as Resend reports it now.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowDown,
  ArrowUp,
  ExternalLink,
  FileText,
  Loader2,
  Mail,
  Paperclip,
  User,
  X,
} from 'lucide-react';
import { api, reportError, type EmailDelivery, type EmailDetail, type EmailLogRow } from './lib';

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

export function timeLabel(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

export function dayLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const date = d.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    ...(d.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}),
  });
  if (same(d, today)) return `Today · ${date}`;
  if (same(d, yesterday)) return `Yesterday · ${date}`;
  return date;
}

function fullDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
      });
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

const TONE: Record<EmailDelivery['tone'], string> = {
  good: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  neutral: 'bg-slate-700/30 text-slate-300 border-slate-600',
  warn: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  bad: 'bg-red-500/15 text-red-300 border-red-500/40',
};

export function DeliveryPill({ d }: { d: EmailDelivery }) {
  return (
    <span
      title={d.explanation}
      className={`inline-flex items-center text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${TONE[d.tone] ?? TONE.neutral}`}
    >
      {d.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// A row of the log
// ---------------------------------------------------------------------------

/** One email in a list: the subject and recipient in full, never cut off. */
export function EmailRow({
  r,
  onOpen,
  selected,
  showDate,
}: {
  r: EmailLogRow;
  onOpen: () => void;
  selected?: boolean;
  /** Show the date as well as the time (lists not grouped by day). */
  showDate?: boolean;
}) {
  const bad = r.delivery.tone === 'bad';
  return (
    <button
      onClick={onOpen}
      className={`w-full text-left px-3 sm:px-4 py-3 flex gap-3 transition-colors ${
        selected ? 'bg-cyan-500/10' : bad ? 'bg-red-950/20 hover:bg-red-950/30' : 'hover:bg-slate-800/40'
      }`}
    >
      <div className="hidden sm:block w-[4.5rem] shrink-0 text-xs text-slate-400 pt-0.5">
        {showDate && (
          <div className="text-slate-500">
            {new Date(r.ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
          </div>
        )}
        {timeLabel(r.ts)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start gap-2">
          <span className="flex-1 min-w-0 text-sm text-slate-100 font-medium break-words">
            {r.subject || '(no subject)'}
          </span>
          <span className="shrink-0">
            <DeliveryPill d={r.delivery} />
          </span>
        </div>
        <div className="mt-0.5 text-xs text-slate-400 break-all">
          {r.to_me ? (
            <span className="text-violet-300">To you</span>
          ) : (
            <>
              To <span className="text-slate-300">{r.recipient}</span>
            </>
          )}
        </div>
        <div className="mt-0.5 text-[11px] text-slate-500 break-words">
          <span className="sm:hidden">
            {showDate &&
              `${new Date(r.ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}, `}
            {timeLabel(r.ts)} ·{' '}
          </span>
          {r.kind_label}
          {r.about?.label ? ` · ${r.about.label}` : ''}
        </div>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// The viewer
// ---------------------------------------------------------------------------

/** The email body in a sandboxed frame, grown to its full height.
 *
 *  sandbox without allow-scripts: nothing in an email can run. allow-same-
 *  origin (safe without scripts) lets this page measure the height;
 *  allow-popups-to-escape-sandbox lets a link open normally in a new tab. */
function EmailFrame({ html }: { html: string }) {
  const ref = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(400);

  // The body's own height, not the document's: a document is never shorter
  // than the frame it sits in, so measuring it could only ever grow.
  const measure = useCallback(() => {
    try {
      const doc = ref.current?.contentDocument;
      const body = doc?.body;
      if (!doc || !body) return;
      const cs = doc.defaultView?.getComputedStyle(body);
      const margins = cs ? parseFloat(cs.marginTop) + parseFloat(cs.marginBottom) : 0;
      setHeight(Math.max(120, Math.ceil(body.getBoundingClientRect().height + margins) + 2));
    } catch {
      /* keep the last height */
    }
  }, []);

  const observer = useRef<ResizeObserver | null>(null);
  useEffect(() => () => observer.current?.disconnect(), []);

  // Grow to the content once it has loaded, and again if it changes size
  // (images arriving late).
  const onLoad = useCallback(() => {
    measure();
    try {
      const doc = ref.current?.contentDocument;
      observer.current?.disconnect();
      if (doc?.body && 'ResizeObserver' in window) {
        observer.current = new ResizeObserver(() => measure());
        observer.current.observe(doc.body);
      }
      doc?.querySelectorAll('img').forEach((img) => img.addEventListener('load', measure));
    } catch {
      /* measuring is a nicety */
    }
  }, [measure]);

  return (
    <iframe
      ref={ref}
      onLoad={onLoad}
      title="Email content"
      sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      srcDoc={`<!doctype html><base target="_blank"><meta charset="utf-8">${html}`}
      style={{ height }}
      className="w-full rounded-lg bg-white border border-slate-700"
    />
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2 py-1.5 border-b border-slate-800/70 last:border-0">
      <dt className="text-xs text-slate-500 pt-0.5">{label}</dt>
      <dd className="text-sm text-slate-200 break-words min-w-0">{children}</dd>
    </div>
  );
}

export function EmailViewer({
  emailId,
  onClose,
  onNewer,
  onOlder,
  onAuthError,
}: {
  emailId: number | null;
  onClose: () => void;
  /** Step through the list the email was opened from. */
  onNewer?: (() => void) | null;
  onOlder?: (() => void) | null;
  onAuthError: () => void;
}) {
  const [data, setData] = useState<EmailDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'email' | 'text'>('email');
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (emailId === null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api<EmailDetail>(`/api/admin/comms/log/${emailId}`)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setTab(d.html ? 'email' : 'text');
        panelRef.current?.scrollTo({ top: 0 });
      })
      .catch((e) => {
        if (!cancelled) reportError(e, onAuthError, setError);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [emailId, onAuthError]);

  // Esc closes; the arrow keys step through the list.
  useEffect(() => {
    if (emailId === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowUp' && onNewer) {
        e.preventDefault();
        onNewer();
      } else if (e.key === 'ArrowDown' && onOlder) {
        e.preventDefault();
        onOlder();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [emailId, onClose, onNewer, onOlder]);

  if (emailId === null) return null;
  const d = data && data.id === emailId ? data : null;

  // Rendered on <body>: inside the admin layout, the site's fixed header
  // would sit on top of the panel.
  return createPortal(
    <div className="fixed inset-0 z-[100] flex justify-end" role="dialog" aria-modal="true" aria-label="Email">
      <button
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-slate-950/70 backdrop-blur-[1px] cursor-default"
      />
      <div
        ref={panelRef}
        className="relative h-full w-full sm:w-[min(820px,94vw)] bg-slate-950 border-l border-slate-800 shadow-2xl overflow-y-auto"
      >
        {/* Toolbar */}
        <div className="sticky top-0 z-10 flex items-center gap-2 px-4 py-3 bg-slate-950/95 border-b border-slate-800">
          <Mail className="w-4 h-4 text-cyan-300" />
          <span className="text-sm text-slate-300">Email</span>
          {loading && <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => onNewer?.()}
              disabled={!onNewer}
              title="Newer email (↑)"
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-30"
            >
              <ArrowUp className="w-3.5 h-3.5" /> Newer
            </button>
            <button
              onClick={() => onOlder?.()}
              disabled={!onOlder}
              title="Older email (↓)"
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-30"
            >
              <ArrowDown className="w-3.5 h-3.5" /> Older
            </button>
            <button
              onClick={onClose}
              title="Close (Esc)"
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800"
            >
              <X className="w-3.5 h-3.5" /> Close
            </button>
          </div>
        </div>

        <div className="p-4 sm:p-6 space-y-5">
          {error && (
            <div className="text-sm text-red-200 border border-red-500/40 bg-red-950/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
          {!d && !error && (
            <div className="py-20 text-center text-sm text-slate-500">
              <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
              Opening the email…
            </div>
          )}

          {d && (
            <>
              <div>
                <div className="text-xs text-slate-500 mb-1">{d.kind_label}</div>
                <h2 className="text-lg sm:text-xl font-semibold text-white break-words">
                  {d.subject || '(no subject)'}
                </h2>
              </div>

              {/* What became of it */}
              <div
                className={`rounded-lg border px-3 py-2.5 text-sm ${
                  d.delivery.tone === 'bad'
                    ? 'border-red-500/40 bg-red-950/30'
                    : d.delivery.tone === 'good'
                      ? 'border-emerald-500/30 bg-emerald-950/20'
                      : d.delivery.tone === 'warn'
                        ? 'border-amber-500/30 bg-amber-950/20'
                        : 'border-slate-700 bg-slate-900/60'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <DeliveryPill d={d.delivery} />
                  <span className="text-slate-200">{d.delivery.explanation}</span>
                </div>
                {/* A not-sent email's reason is already the explanation above. */}
                {d.error && d.delivery.state !== 'not_sent' && (
                  <div className="mt-1 text-xs text-red-300 break-words">{d.error}</div>
                )}
                {(d.delivery.checked_at || d.lookup_error) && (
                  <div className="mt-1 text-[11px] text-slate-500">
                    {d.delivery.checked_at &&
                      `Status from Resend, checked ${fullDate(d.delivery.checked_at)}. `}
                    {d.lookup_error && `Couldn't check with Resend just now: ${d.lookup_error}.`}
                  </div>
                )}
              </div>

              {/* Headers */}
              <dl className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1">
                <Field label="Sent">{fullDate(d.ts)}</Field>
                <Field label="From">{d.from_addr || <span className="text-slate-500">not recorded</span>}</Field>
                <Field label="To">
                  <span className="break-all">{d.recipient}</span>
                  {d.to_me && <span className="ml-2 text-xs text-violet-300">(you)</span>}
                  {d.learner && (
                    <a
                      href={`#students/${d.learner.id}`}
                      onClick={onClose}
                      className="ml-2 inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline"
                    >
                      <User className="w-3 h-3" />
                      {d.learner.name || 'Student'} — student page
                    </a>
                  )}
                </Field>
                {d.cc && (
                  <Field label="Cc">
                    <span className="break-all">{d.cc}</span>
                  </Field>
                )}
                {d.bcc && (
                  <Field label="Bcc">
                    <span className="break-all">{d.bcc}</span>
                  </Field>
                )}
                {d.reply_to && (
                  <Field label="Replies to">
                    <span className="break-all">{d.reply_to}</span>
                  </Field>
                )}
                {d.about.label && (
                  <Field label="About">
                    {d.about.href ? (
                      <a
                        href={d.about.href}
                        onClick={onClose}
                        className="inline-flex items-center gap-1 text-cyan-300 hover:underline"
                      >
                        {d.about.label}
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : (
                      d.about.label
                    )}
                  </Field>
                )}
                {d.attachments.length > 0 && (
                  <Field label="Attached">
                    {d.attachments.map((a) => (
                      <span key={a} className="inline-flex items-center gap-1 mr-3">
                        <Paperclip className="w-3 h-3 text-slate-400" />
                        {a}
                      </span>
                    ))}
                  </Field>
                )}
                {d.provider_id && (
                  <Field label="Resend id">
                    <span className="font-mono text-xs text-slate-400 break-all">{d.provider_id}</span>
                  </Field>
                )}
              </dl>

              {/* The email itself */}
              {d.copy.available ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5">
                    {d.html && (
                      <button
                        onClick={() => setTab('email')}
                        className={`text-xs px-3 py-1.5 rounded-lg border ${
                          tab === 'email'
                            ? 'bg-cyan-500/15 text-cyan-200 border-cyan-500/40'
                            : 'text-slate-400 border-slate-800 hover:text-white'
                        }`}
                      >
                        <Mail className="w-3.5 h-3.5 inline mr-1" />
                        As the recipient sees it
                      </button>
                    )}
                    {d.text && (
                      <button
                        onClick={() => setTab('text')}
                        className={`text-xs px-3 py-1.5 rounded-lg border ${
                          tab === 'text'
                            ? 'bg-cyan-500/15 text-cyan-200 border-cyan-500/40'
                            : 'text-slate-400 border-slate-800 hover:text-white'
                        }`}
                      >
                        <FileText className="w-3.5 h-3.5 inline mr-1" />
                        Plain text
                      </button>
                    )}
                  </div>
                  {tab === 'email' && d.html ? (
                    <EmailFrame key={d.id} html={d.html} />
                  ) : (
                    <pre className="whitespace-pre-wrap break-words text-sm text-slate-200 bg-slate-900/70 border border-slate-800 rounded-lg p-4 font-sans">
                      {d.text}
                    </pre>
                  )}
                  {(d.html + d.text).includes('=(hidden)') && (
                    <p className="text-[11px] text-slate-500">
                      The sign-in link in this email is shown with its key hidden, so it can't sign
                      anyone in from here.
                    </p>
                  )}
                </div>
              ) : (
                <div className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-3 text-sm text-slate-300">
                  {d.copy.note}
                  {d.scope_kind === 'support' && d.about.href && (
                    <a
                      href={d.about.href}
                      onClick={onClose}
                      className="ml-1 text-cyan-300 hover:underline"
                    >
                      Open the ticket.
                    </a>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Viewer state for a list: which email is open, and stepping through the list. */
export function useEmailViewer(rows: EmailLogRow[]) {
  const [openId, setOpenId] = useState<number | null>(null);
  const idx = openId === null ? -1 : rows.findIndex((r) => r.id === openId);
  return {
    openId,
    open: (id: number) => setOpenId(id),
    close: () => setOpenId(null),
    newer: idx > 0 ? () => setOpenId(rows[idx - 1].id) : null,
    older: idx >= 0 && idx < rows.length - 1 ? () => setOpenId(rows[idx + 1].id) : null,
  };
}
