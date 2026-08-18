/**
 * Support — the inbox and the conversation.
 *
 * Two views behind one hash route: a queue (#support) and a thread
 * (#support/<ref>). The queue answers "what needs me?"; the thread is
 * where the issue actually gets solved, with the customer's account
 * state on screen so a reply can be specific rather than apologetic.
 *
 * The AI is present in three places and never sends on its own:
 *   - it has already triaged and, for safe categories, already answered
 *     (those turns appear in the thread, labelled)
 *   - "Draft a reply" fills the composer for you to edit
 *   - "Re-triage" re-runs classification after you've edited the notes
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArchiveX,
  ArrowLeft,
  Ban,
  Bot,
  Check,
  CheckCircle2,
  Inbox,
  Loader2,
  Mail,
  MailWarning,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Sparkles,
  StickyNote,
  User,
} from 'lucide-react';
import {
  api,
  formatDate,
  money,
  plainTextToEmailHtml,
  reportError,
  SUPPORT_STATUS_LABEL,
  type SupportDraft,
  type SupportSettings,
  type SupportStats,
  type SupportTicket,
  type SupportTicketDetail,
  type ViewState,
} from './lib';
import { EmptyState, Notice, RefreshButton, Section } from './ui';

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

/** Escalated is the only status that means "a human is the bottleneck", so
 *  it is the only one that gets an alarm colour. Everything else is calm. */
const STATUS_STYLE: Record<string, string> = {
  new: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
  ai_handling: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  awaiting_customer: 'bg-amber-500/10 text-amber-300 border-amber-500/25',
  escalated: 'bg-red-500/15 text-red-300 border-red-500/35',
  auto_resolved: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25',
  resolved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  archived: 'bg-slate-700/30 text-slate-400 border-slate-700',
  spam: 'bg-slate-800/60 text-slate-500 border-slate-700',
};

function StatusPill({ status }: { status: string }) {
  const cls = STATUS_STYLE[status] ?? 'bg-slate-700/30 text-slate-300 border-slate-700';
  return (
    <span className={`inline-flex items-center text-[11px] px-2 py-0.5 rounded-full border ${cls}`}>
      {SUPPORT_STATUS_LABEL[status] ?? status}
    </span>
  );
}

function PriorityPill({ priority, label }: { priority: number; label: string }) {
  const cls =
    priority <= 2
      ? 'bg-red-500/15 text-red-300 border-red-500/30'
      : priority <= 4
        ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
        : 'bg-slate-700/40 text-slate-300 border-slate-700';
  return (
    <span className={`inline-flex items-center text-[11px] px-2 py-0.5 rounded-full border ${cls}`}>
      P{priority} {label}
    </span>
  );
}

function relative(iso: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(iso);
}


/**
 * Turn an AI draft back into editable prose.
 *
 * Drafts arrive as HTML, but nobody wants to edit `<p>` tags in a textarea —
 * and the composer already converts plain text to email HTML on send, so
 * round-tripping through text loses nothing that matters. Only links are
 * worth preserving explicitly, since plainTextToEmailHtml re-linkifies bare
 * URLs on the way back out.
 */
function htmlToEditableText(html: string): string {
  if (!html) return '';
  if (!/<[a-z][\s\S]*>/i.test(html)) return html; // already plain
  return html
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<\/\s*p\s*>/gi, '\n\n')
    .replace(/<\/\s*li\s*>/gi, '\n')
    .replace(/<\s*li[^>]*>/gi, '• ')
    .replace(/<a[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)<\/a>/gi, (_m, href, label) => {
      const text = String(label).replace(/<[^>]+>/g, '').trim();
      return text && text !== href ? `${text} (${href})` : String(href);
    })
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SupportPage({
  refOpen,
  go,
  onAuthError,
}: {
  refOpen: string | null;
  go: (v: ViewState, opts?: { replace?: boolean }) => void;
  onAuthError: () => void;
}) {
  if (refOpen) {
    return (
      <TicketThread
        key={refOpen}
        ticketRef={refOpen}
        onBack={() => go({ page: 'support' })}
        onAuthError={onAuthError}
      />
    );
  }
  return <Inbox_ go={go} onAuthError={onAuthError} />;
}

// ---------------------------------------------------------------------------
// Inbox
// ---------------------------------------------------------------------------

const FILTERS: { key: string; label: string }[] = [
  { key: 'open', label: 'Open' },
  { key: 'escalated', label: 'Needs you' },
  { key: 'awaiting_customer', label: 'Awaiting reply' },
  { key: 'auto_resolved', label: 'Auto-resolved' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'archived', label: 'Archived' },
  { key: 'spam', label: 'Spam' },
];

function Inbox_({
  go,
  onAuthError,
}: {
  go: (v: ViewState, opts?: { replace?: boolean }) => void;
  onAuthError: () => void;
}) {
  const [tickets, setTickets] = useState<SupportTicket[] | null>(null);
  const [stats, setStats] = useState<SupportStats | null>(null);
  const [filter, setFilter] = useState('open');
  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: '200' });
      // A search should look everywhere, including archived and spam —
      // "where did that email go?" is exactly when you search.
      if (query.trim()) params.set('q', query.trim());
      else params.set('status_filter', filter);
      const [list, s] = await Promise.all([
        api<{ total: number; items: SupportTicket[] }>(
          `/api/admin/support/tickets?${params.toString()}`,
        ),
        api<SupportStats>('/api/admin/support/stats'),
      ]);
      setTickets(list.items);
      setStats(s);
      setSelected(new Set());
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [filter, query, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function bulk(action: 'archive' | 'resolve' | 'spam') {
    const refs = [...selected];
    if (!refs.length) return;
    const verb = action === 'spam' ? 'mark as spam' : action;
    if (!window.confirm(`${verb} ${refs.length} ticket${refs.length === 1 ? '' : 's'}?`)) return;
    setBusy(true);
    try {
      await api('/api/admin/support/tickets/bulk', {
        method: 'POST',
        body: JSON.stringify({ refs, action }),
      });
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(false);
    }
  }

  const rows = tickets ?? [];
  const allSelected = rows.length > 0 && selected.size === rows.length;

  return (
    <div className="space-y-6">
      <Section
        icon={<Inbox className="w-5 h-5 text-cyan-300" />}
        title="Support"
        sub={
          stats
            ? `${stats.open} open · ${stats.needs_human} waiting on you · ${stats.total} all time`
            : 'Customer conversations, triaged automatically.'
        }
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSettings((v) => !v)}
              className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors"
            >
              <Settings2 className="w-3.5 h-3.5" />
              Settings
            </button>
            <RefreshButton onClick={() => void load()} loading={loading} />
          </div>
        }
      >
        {error && <Notice kind="error">{error}</Notice>}

        {stats && stats.needs_human > 0 && filter !== 'escalated' && !query && (
          <button
            onClick={() => setFilter('escalated')}
            className="w-full mb-4 flex items-center gap-2 text-left text-sm px-3 py-2.5 rounded-lg border border-red-500/30 bg-red-950/25 text-red-200 hover:bg-red-950/40 transition-colors"
          >
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>
              <strong>{stats.needs_human}</strong>{' '}
              {stats.needs_human === 1 ? 'ticket needs' : 'tickets need'} a human reply — the
              assistant escalated them rather than guess.
            </span>
          </button>
        )}

        {/* Filters + search */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {FILTERS.map((f) => {
            const count =
              f.key === 'open' ? stats?.open : stats?.by_status?.[f.key];
            const active = filter === f.key && !query;
            return (
              <button
                key={f.key}
                onClick={() => {
                  setFilter(f.key);
                  setQuery('');
                  setQueryInput('');
                }}
                className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
                  active
                    ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'
                    : 'text-slate-400 border-slate-800 hover:text-white hover:bg-slate-800/60'
                }`}
              >
                {f.label}
                {count ? <span className="ml-1.5 opacity-70">{count}</span> : null}
              </button>
            );
          })}

          <form
            className="ml-auto relative"
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(queryInput);
            }}
          >
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="Search ref, email, subject…"
              className="w-56 bg-slate-900/70 border border-slate-800 rounded-lg pl-8 pr-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50"
            />
          </form>
        </div>

        {query && (
          <div className="mb-3 text-xs text-slate-400">
            Searching all tickets for “{query}”.{' '}
            <button
              className="text-cyan-400 hover:underline"
              onClick={() => {
                setQuery('');
                setQueryInput('');
              }}
            >
              Clear
            </button>
          </div>
        )}

        {/* Bulk bar — only present when something is selected. */}
        {selected.size > 0 && (
          <div className="mb-3 flex items-center gap-2 text-xs px-3 py-2 rounded-lg border border-cyan-500/25 bg-cyan-500/5">
            <span className="text-cyan-200">{selected.size} selected</span>
            <div className="ml-auto flex items-center gap-1.5">
              <button
                disabled={busy}
                onClick={() => void bulk('resolve')}
                className="px-2 py-1 rounded border border-emerald-600/40 text-emerald-300 hover:bg-emerald-950/40 disabled:opacity-50"
              >
                Resolve
              </button>
              <button
                disabled={busy}
                onClick={() => void bulk('archive')}
                className="px-2 py-1 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                Archive
              </button>
              <button
                disabled={busy}
                onClick={() => void bulk('spam')}
                className="px-2 py-1 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 disabled:opacity-50"
              >
                Spam
              </button>
            </div>
          </div>
        )}

        {loading && !tickets ? (
          <div className="py-16 text-center text-slate-500 text-sm">
            <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
            Loading tickets…
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Inbox className="w-6 h-6 text-slate-600" />}
            title={query ? 'Nothing matched that search' : 'Nothing here'}
            hint={
              query
                ? 'Try the ticket ref, or part of the sender’s email address.'
                : filter === 'open'
                  ? 'No open conversations. Customer messages from the contact form, the learner portal and inbound email land here automatically.'
                  : 'No tickets with this status.'
            }
          />
        ) : (
          <div className="border border-slate-800 rounded-xl overflow-hidden">
            <div className="flex items-center gap-3 px-3 py-2 bg-slate-900/60 border-b border-slate-800 text-[11px] uppercase tracking-wide text-slate-500">
              <input
                type="checkbox"
                aria-label="Select all"
                checked={allSelected}
                onChange={(e) =>
                  setSelected(e.target.checked ? new Set(rows.map((t) => t.ref)) : new Set())
                }
                className="accent-cyan-500"
              />
              <span className="flex-1">Conversation</span>
              <span className="hidden md:block w-40">Category</span>
              <span className="hidden sm:block w-36">Status</span>
              <span className="w-20 text-right">Last</span>
            </div>

            <div className="divide-y divide-slate-800/70">
              {rows.map((t) => (
                <div
                  key={t.ref}
                  className={`flex items-center gap-3 px-3 py-2.5 hover:bg-slate-800/40 transition-colors ${
                    t.needs_reply ? 'bg-slate-900/40' : ''
                  }`}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ticket ${t.ref}`}
                    checked={selected.has(t.ref)}
                    onChange={(e) => {
                      const next = new Set(selected);
                      if (e.target.checked) next.add(t.ref);
                      else next.delete(t.ref);
                      setSelected(next);
                    }}
                    className="accent-cyan-500 shrink-0"
                  />

                  <button
                    onClick={() => go({ page: 'support', ref: t.ref })}
                    className="flex-1 min-w-0 text-left"
                  >
                    <div className="flex items-center gap-2">
                      {t.needs_reply && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-cyan-400 shrink-0"
                          title="The customer spoke last"
                        />
                      )}
                      <span
                        className={`truncate text-sm ${
                          t.needs_reply ? 'text-white font-medium' : 'text-slate-200'
                        }`}
                      >
                        {t.subject}
                      </span>
                      <span className="text-[10px] text-slate-600 font-mono shrink-0">
                        #{t.ref}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 truncate">
                      {t.submitter_name ? `${t.submitter_name} · ` : ''}
                      {t.submitter_email}
                      {t.summary ? ` — ${t.summary}` : ''}
                    </div>
                  </button>

                  <div className="hidden md:block w-40 shrink-0">
                    <PriorityPill priority={t.priority} label={t.category_label} />
                  </div>
                  <div className="hidden sm:block w-36 shrink-0">
                    <StatusPill status={t.status} />
                  </div>
                  <div className="w-20 text-right text-xs text-slate-500 shrink-0">
                    {relative(t.last_message_at)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {showSettings && <SupportSettingsPanel onAuthError={onAuthError} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thread
// ---------------------------------------------------------------------------

function TicketThread({
  ticketRef,
  onBack,
  onAuthError,
}: {
  ticketRef: string;
  onBack: () => void;
  onAuthError: () => void;
}) {
  const [data, setData] = useState<SupportTicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const [reply, setReply] = useState('');
  const [rawHtml, setRawHtml] = useState(false);
  const [closeAfter, setCloseAfter] = useState(true);
  const [sending, setSending] = useState(false);

  const [instruction, setInstruction] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [gaps, setGaps] = useState<string[]>([]);

  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(
        await api<SupportTicketDetail>(
          `/api/admin/support/tickets/${encodeURIComponent(ticketRef)}`,
        ),
      );
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [ticketRef, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  function flashFor(msg: string) {
    setFlash(msg);
    window.setTimeout(() => setFlash(null), 6000);
  }

  async function send() {
    if (!reply.trim()) return;
    setSending(true);
    setError(null);
    try {
      const res = await api<{ delivered: boolean; status: string; warning: string }>(
        `/api/admin/support/tickets/${encodeURIComponent(ticketRef)}/reply`,
        {
          method: 'POST',
          body: JSON.stringify({
            body_html: rawHtml ? reply : plainTextToEmailHtml(reply),
            set_status: closeAfter ? 'resolved' : 'awaiting_customer',
          }),
        },
      );
      if (res.delivered) {
        setReply('');
        setGaps([]);
        flashFor(closeAfter ? 'Reply sent and ticket resolved.' : 'Reply sent.');
      } else {
        setError(res.warning || 'The email could not be sent.');
      }
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSending(false);
    }
  }

  async function draft() {
    setDrafting(true);
    setError(null);
    try {
      const res = await api<SupportDraft>(
        `/api/admin/support/tickets/${encodeURIComponent(ticketRef)}/draft`,
        { method: 'POST', body: JSON.stringify({ instruction: instruction.trim() }) },
      );
      // Drafts arrive as HTML but are edited as prose — see
      // htmlToEditableText. The composer converts back on send.
      setReply(htmlToEditableText(res.reply_html));
      setRawHtml(false);
      setGaps(res.needs_from_admin ?? []);
      setInstruction('');
      composerRef.current?.focus();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setDrafting(false);
    }
  }

  async function patch(body: Record<string, unknown>, msg: string) {
    setBusy(true);
    try {
      await api(`/api/admin/support/tickets/${encodeURIComponent(ticketRef)}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      flashFor(msg);
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    if (!note.trim()) return;
    setBusy(true);
    try {
      await api(`/api/admin/support/tickets/${encodeURIComponent(ticketRef)}/note`, {
        method: 'POST',
        body: JSON.stringify({ body: note.trim() }),
      });
      setNote('');
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(false);
    }
  }

  async function retriage() {
    setBusy(true);
    try {
      await api(`/api/admin/support/tickets/${encodeURIComponent(ticketRef)}/retriage`, {
        method: 'POST',
      });
      flashFor('Re-triaging — refresh in a moment to see the result.');
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) {
    return (
      <div className="py-24 text-center text-slate-500 text-sm">
        <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
        Loading conversation…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="space-y-4">
        {error && <Notice kind="error">{error}</Notice>}
        <button onClick={onBack} className="text-sm text-cyan-400 hover:underline">
          ← Back to Support
        </button>
      </div>
    );
  }

  const t = data.ticket;

  return (
    <div className="space-y-4">
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Support
      </button>

      {error && <Notice kind="error">{error}</Notice>}
      {flash && <Notice kind="success">{flash}</Notice>}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-4">
        {/* ---------------- Conversation ---------------- */}
        <div className="space-y-4">
          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 sm:p-5">
            <div className="flex flex-wrap items-start gap-3 mb-3">
              <div className="min-w-0 flex-1">
                <h2 className="text-lg font-semibold text-white truncate">{t.subject}</h2>
                <p className="text-sm text-slate-400 truncate">
                  {t.submitter_name ? `${t.submitter_name} · ` : ''}
                  <a
                    href={`mailto:${t.submitter_email}`}
                    className="text-cyan-400 hover:underline"
                  >
                    {t.submitter_email}
                  </a>
                  <span className="text-slate-600 font-mono ml-2">#{t.ref}</span>
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <PriorityPill priority={t.priority} label={t.category_label} />
                <StatusPill status={t.status} />
              </div>
            </div>

            {data.ai_result?.summary && (
              <div className="flex items-start gap-2 text-xs text-slate-400 bg-slate-950/50 border border-slate-800 rounded-lg px-3 py-2">
                <Bot className="w-3.5 h-3.5 mt-0.5 shrink-0 text-violet-300" />
                <span>
                  {data.ai_result.summary}
                  {data.ai_result.escalation_reason ? (
                    <span className="text-slate-500"> — {data.ai_result.escalation_reason}</span>
                  ) : null}
                  {typeof data.ai_result.confidence === 'number' && (
                    <span className="text-slate-600">
                      {' '}
                      ({Math.round(data.ai_result.confidence * 100)}% confidence)
                    </span>
                  )}
                </span>
              </div>
            )}
          </div>

          <div className="space-y-3">
            {data.messages.map((m) => (
              <MessageBubble key={m.id} m={m} />
            ))}
          </div>

          {/* ---------------- Composer ---------------- */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 sm:p-5 space-y-3">
            <div className="flex items-center gap-2">
              <Send className="w-4 h-4 text-cyan-300" />
              <h3 className="text-sm font-semibold text-white">Reply to {t.submitter_name || t.submitter_email}</h3>
            </div>

            {/* Ask the AI. The instruction box is what makes this useful —
                "offer him a call", "explain the 14-day window" — rather than
                a generic draft you rewrite anyway. */}
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !drafting) void draft();
                }}
                placeholder="Tell the assistant how to answer (optional) — e.g. “offer a 20-min call”"
                className="flex-1 bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-violet-500/50"
              />
              <button
                onClick={() => void draft()}
                disabled={drafting}
                className="inline-flex items-center justify-center gap-1.5 text-sm px-3 py-2 rounded-lg border border-violet-500/40 text-violet-200 bg-violet-500/10 hover:bg-violet-500/20 disabled:opacity-50 transition-colors shrink-0"
              >
                {drafting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                Draft a reply
              </button>
            </div>

            {gaps.length > 0 && (
              <div className="text-xs bg-amber-950/30 border border-amber-900/50 text-amber-200 rounded-lg px-3 py-2">
                <div className="font-medium mb-1">The assistant needs you to confirm:</div>
                <ul className="list-disc list-inside space-y-0.5">
                  {gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
              </div>
            )}

            <textarea
              ref={composerRef}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={8}
              placeholder="Write your reply. Plain text is fine — it's converted to email HTML."
              className="w-full bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 font-mono focus:outline-none focus:border-cyan-500/50"
            />

            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400">
              <label className="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={rawHtml}
                  onChange={(e) => setRawHtml(e.target.checked)}
                  className="accent-cyan-500"
                />
                Send as raw HTML
              </label>
              <label className="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={closeAfter}
                  onChange={(e) => setCloseAfter(e.target.checked)}
                  className="accent-cyan-500"
                />
                Mark resolved after sending
              </label>
              <button
                onClick={() => void send()}
                disabled={sending || !reply.trim()}
                className="ml-auto inline-flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                Send reply
              </button>
            </div>
            <p className="text-[11px] text-slate-600">
              Goes out from info@mail.proreadyengineer.com with ticket #{t.ref} in the subject —
              their reply comes back to this thread.
            </p>
          </div>

          {/* ---------------- Internal note ---------------- */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 space-y-2">
            <div className="flex items-center gap-2">
              <StickyNote className="w-4 h-4 text-amber-300" />
              <h3 className="text-sm font-semibold text-white">Internal note</h3>
              <span className="text-xs text-slate-500">never emailed</span>
            </div>
            <div className="flex gap-2">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void saveNote();
                }}
                placeholder="Called him, invoice re-sent…"
                className="flex-1 bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40"
              />
              <button
                onClick={() => void saveNote()}
                disabled={busy || !note.trim()}
                className="text-sm px-3 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
              >
                Add
              </button>
            </div>
          </div>
        </div>

        {/* ---------------- Sidebar ---------------- */}
        <div className="space-y-4">
          <ActionsCard
            ticket={t}
            busy={busy}
            onPatch={patch}
            onRetriage={retriage}
            onRefresh={() => void load()}
            loading={loading}
          />
          <CustomerCard detail={data} />
          <TimelineCard detail={data} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thread pieces
// ---------------------------------------------------------------------------

function MessageBubble({ m }: { m: SupportTicketDetail['messages'][number] }) {
  const isCustomer = m.sender_kind === 'customer';
  const isNote = m.sender_kind === 'note';
  const isAi = m.sender_kind === 'ai';

  const shell = isNote
    ? 'bg-amber-950/20 border-amber-900/40'
    : isCustomer
      ? 'bg-slate-900/80 border-slate-800'
      : isAi
        ? 'bg-violet-950/20 border-violet-900/40'
        : 'bg-cyan-950/20 border-cyan-900/40';

  const icon = isNote ? (
    <StickyNote className="w-3.5 h-3.5 text-amber-300" />
  ) : isCustomer ? (
    <User className="w-3.5 h-3.5 text-slate-400" />
  ) : isAi ? (
    <Bot className="w-3.5 h-3.5 text-violet-300" />
  ) : (
    <Mail className="w-3.5 h-3.5 text-cyan-300" />
  );

  const who = isNote
    ? 'Internal note'
    : isAi
      ? 'Assistant (automatic)'
      : m.sender_name || (isCustomer ? 'Customer' : 'You');

  return (
    <div
      className={`border rounded-xl p-3.5 ${shell} ${isCustomer ? '' : 'sm:ml-8'}`}
    >
      <div className="flex items-center gap-2 mb-2 text-xs">
        {icon}
        <span className="font-medium text-slate-300">{who}</span>
        <span className="text-slate-600">{relative(m.created_at)}</span>
        {m.email_delivered === false && (
          <span
            className="ml-auto inline-flex items-center gap-1 text-red-300"
            title="Resend rejected this send — the customer never received it"
          >
            <MailWarning className="w-3.5 h-3.5" />
            not delivered
          </span>
        )}
      </div>
      {/* Customer mail is rendered as text, never as their HTML — an inbound
          message is untrusted content and must not execute in the panel. */}
      {m.body_text || !m.body_html ? (
        <p className="text-sm text-slate-200 whitespace-pre-wrap break-words">
          {m.body_text || '(empty message)'}
        </p>
      ) : (
        <p className="text-sm text-slate-200 whitespace-pre-wrap break-words">
          {m.body_html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() || '(empty message)'}
        </p>
      )}
    </div>
  );
}

const CATEGORY_OPTIONS = [
  'payment',
  'access',
  'bug',
  'business',
  'enrollment',
  'course_info',
  'software',
  'general',
];

function ActionsCard({
  ticket,
  busy,
  onPatch,
  onRetriage,
  onRefresh,
  loading,
}: {
  ticket: SupportTicket;
  busy: boolean;
  onPatch: (body: Record<string, unknown>, msg: string) => Promise<void>;
  onRetriage: () => Promise<void>;
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Actions</h3>
        <RefreshButton onClick={onRefresh} loading={loading} />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          disabled={busy || ticket.status === 'resolved'}
          onClick={() => void onPatch({ status: 'resolved' }, 'Marked resolved.')}
          className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-lg border border-emerald-600/40 text-emerald-300 hover:bg-emerald-950/40 disabled:opacity-40"
        >
          <CheckCircle2 className="w-3.5 h-3.5" />
          Resolve
        </button>
        <button
          disabled={busy || ticket.status === 'escalated'}
          onClick={() => void onPatch({ status: 'escalated' }, 'Flagged for follow-up.')}
          className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-lg border border-red-600/40 text-red-300 hover:bg-red-950/40 disabled:opacity-40"
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          Needs me
        </button>
        <button
          disabled={busy}
          onClick={() => void onPatch({ status: 'archived' }, 'Archived.')}
          className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
        >
          <ArchiveX className="w-3.5 h-3.5" />
          Archive
        </button>
        <button
          disabled={busy}
          onClick={() =>
            void onPatch(
              { status: ticket.status === 'spam' ? 'new' : 'spam' },
              ticket.status === 'spam' ? 'Restored from spam.' : 'Marked as spam.',
            )
          }
          className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800 disabled:opacity-40"
        >
          <Ban className="w-3.5 h-3.5" />
          {ticket.status === 'spam' ? 'Not spam' : 'Spam'}
        </button>
      </div>

      <label className="block">
        <span className="text-xs text-slate-500">Category</span>
        <select
          value={ticket.category}
          disabled={busy}
          onChange={(e) => void onPatch({ category: e.target.value }, 'Category updated.')}
          className="mt-1 w-full bg-slate-950/70 border border-slate-800 rounded-lg px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50"
        >
          {CATEGORY_OPTIONS.map((c) => (
            <option key={c} value={c}>
              {c.replace('_', ' ')}
            </option>
          ))}
        </select>
      </label>

      <button
        disabled={busy}
        onClick={() => void onRetriage()}
        className="w-full inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-lg border border-violet-500/30 text-violet-200 hover:bg-violet-500/10 disabled:opacity-40"
        title="Re-run classification — useful after editing the support notes"
      >
        <RefreshCw className="w-3.5 h-3.5" />
        Re-triage with AI
      </button>

      <p className="text-[11px] text-slate-600">
        Opened {relative(ticket.created_at)} via {ticket.source.replace('_', ' ')}
        {ticket.ai_attempt_count > 0
          ? ` · ${ticket.ai_attempt_count} automated ${ticket.ai_attempt_count === 1 ? 'turn' : 'turns'}`
          : ''}
      </p>
    </div>
  );
}

function CustomerCard({ detail }: { detail: SupportTicketDetail }) {
  const c = detail.customer ?? {};
  const regs = c.registrations ?? [];
  const enrolls = c.enrollments ?? [];
  const orders = c.orders ?? [];
  const prior = (c.prior_tickets ?? []).filter((p) => p.ref !== detail.ticket.ref);

  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 space-y-3">
      <h3 className="text-sm font-semibold text-white">Customer</h3>

      {!c.known && !prior.length ? (
        <p className="text-xs text-slate-500">
          No account, registration or order under this address — most likely a prospect.
        </p>
      ) : null}

      {regs.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
            Cohort registrations
          </div>
          <ul className="space-y-1.5">
            {regs.map((r) => (
              <li key={r.id} className="text-xs">
                <div className="flex items-center gap-1.5">
                  <span
                    className={
                      r.status === 'paid'
                        ? 'text-emerald-300'
                        : r.status === 'cancelled'
                          ? 'text-slate-500'
                          : 'text-amber-300'
                    }
                  >
                    {r.status === 'paid' ? <Check className="w-3 h-3 inline" /> : null} {r.status}
                  </span>
                  <span className="text-slate-300 truncate">{r.course_title}</span>
                </div>
                {r.company && <div className="text-slate-600">{r.company}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {enrolls.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
            Recorded courses
          </div>
          <ul className="space-y-1">
            {enrolls.map((e) => (
              <li key={e.product_code} className="text-xs text-slate-300 truncate">
                <span
                  className={e.status === 'active' ? 'text-emerald-300' : 'text-slate-500'}
                >
                  {e.status}
                </span>{' '}
                {e.product_title}
              </li>
            ))}
          </ul>
        </div>
      )}

      {orders.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Orders</div>
          <ul className="space-y-1">
            {orders.slice(0, 5).map((o) => (
              <li key={o.id} className="text-xs text-slate-400 flex items-center gap-1.5">
                <span className={o.status === 'paid' ? 'text-emerald-300' : 'text-amber-300'}>
                  {o.status}
                </span>
                <span className="truncate">{o.product_code}</span>
                {typeof o.amount_cents === 'number' && (
                  <span className="ml-auto text-slate-500">{money(o.amount_cents)}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {prior.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
            Earlier tickets
          </div>
          <ul className="space-y-1">
            {prior.slice(0, 5).map((p) => (
              <li key={p.ref} className="text-xs">
                <a
                  href={`#support/${p.ref}`}
                  className="text-slate-400 hover:text-cyan-300 truncate block"
                >
                  <span className="font-mono text-slate-600">#{p.ref}</span> {p.subject}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const EVENT_LABEL: Record<string, string> = {
  created: 'Ticket opened',
  ai_classified: 'Classified by AI',
  ai_replied: 'AI replied',
  auto_resolved: 'Auto-resolved',
  escalated: 'Escalated to you',
  admin_reply: 'You replied',
  customer_reply: 'Customer replied',
  status_change: 'Status changed',
  note: 'Note added',
  spam_flagged: 'Flagged as spam',
  reopened: 'Reopened',
  ai_draft: 'AI drafted a reply',
};

function TimelineCard({ detail }: { detail: SupportTicketDetail }) {
  const [open, setOpen] = useState(false);
  const events = detail.events ?? [];
  const shown = open ? events : events.slice(-6);

  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">History</h3>
        {events.length > 6 && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="text-[11px] text-cyan-400 hover:underline"
          >
            {open ? 'Show less' : `All ${events.length}`}
          </button>
        )}
      </div>
      <ol className="space-y-2">
        {shown.map((e) => (
          <li key={e.id} className="text-xs flex gap-2">
            <span className="w-1 h-1 rounded-full bg-slate-600 mt-1.5 shrink-0" />
            <span className="text-slate-400">
              {EVENT_LABEL[e.event_type] ?? e.event_type}
              {e.actor ? <span className="text-slate-600"> · {e.actor}</span> : null}
              <span className="text-slate-600"> · {relative(e.created_at)}</span>
              {typeof e.payload?.reason === 'string' && (
                <span className="block text-slate-600">{e.payload.reason as string}</span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

function SupportSettingsPanel({ onAuthError }: { onAuthError: () => void }) {
  const [s, setS] = useState<SupportSettings | null>(null);
  const [apiUrl, setApiUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [kb, setKb] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<SupportSettings>('/api/admin/support/settings');
      setS(data);
      setApiUrl(data.api_url);
      setModel(data.model_name);
      setKb(data.kb_text);
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const data = await api<SupportSettings>('/api/admin/support/settings', {
        method: 'PUT',
        body: JSON.stringify({
          api_url: apiUrl,
          api_key: apiKey, // blank keeps the stored key
          model_name: model,
          kb_text: kb,
        }),
      });
      setS(data);
      setApiKey('');
      setFlash('Saved.');
      window.setTimeout(() => setFlash(null), 4000);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSaving(false);
    }
  }

  const autoCats = (s?.categories ?? []).filter((c) => c.auto);
  const humanCats = (s?.categories ?? []).filter((c) => !c.auto);

  return (
    <Section
      icon={<Settings2 className="w-5 h-5 text-cyan-300" />}
      title="Support settings"
      sub="What the assistant is allowed to say, and which model says it."
    >
      {error && <Notice kind="error">{error}</Notice>}
      {flash && <Notice kind="success">{flash}</Notice>}

      {s && !s.llm_available && (
        <Notice kind="warn">
          No AI provider is configured, so every ticket is acknowledged and escalated to you
          rather than answered. Set a model below, or configure the AI Assistant and support
          will borrow its credentials.
        </Notice>
      )}
      {s?.llm_available && !s.using_own_credentials && (
        <Notice kind="success">
          Using the AI Assistant’s provider and model. Fill in the fields below only if you want
          support triage to run on a different (cheaper or faster) model.
        </Notice>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs text-slate-500">API base URL</span>
            <input
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="https://api.deepinfra.com/v1/openai"
              className="mt-1 w-full bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50"
            />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500">
              API key {s?.api_key_masked ? `(stored: ${s.api_key_masked})` : ''}
            </span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={s?.api_key_masked ? 'Leave blank to keep the stored key' : 'Paste the key'}
              className="mt-1 w-full bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50"
            />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500">Model</span>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="moonshotai/Kimi-K2.5"
              className="mt-1 w-full bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50"
            />
          </label>

          <div className="text-xs text-slate-500 space-y-1.5 pt-1">
            <div className="text-slate-400 font-medium">Routing</div>
            <p>
              <span className="text-red-300">Always you:</span>{' '}
              {humanCats.map((c) => c.label).join(', ')} — anything about money, blocked access,
              a fault, or a sales lead.
            </p>
            <p>
              <span className="text-emerald-300">AI may answer:</span>{' '}
              {autoCats.map((c) => c.label).join(', ')} — and only when it's confident and the
              answer is in your notes or the live data.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-xs text-slate-500">
              What the assistant is allowed to tell customers
            </span>
            <textarea
              value={kb}
              onChange={(e) => setKb(e.target.value)}
              rows={16}
              placeholder={
                'Facts and policy the auto-replier may state. For example:\n\n' +
                '- Refunds: full refund up to 14 days before a cohort starts.\n' +
                '- Recordings: every live cohort is recorded; enrolled seats keep access for 12 months.\n' +
                '- Certificates: issued after the final assessment is passed.\n' +
                '- Prerequisites: undergraduate thermodynamics; no CFD experience needed.\n' +
                '- Invoices: bank transfer available on request for company purchases.'
              }
              className="mt-1 w-full bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50"
            />
          </label>
          <p className="text-[11px] text-slate-600">
            Anything not written here and not in the database, the assistant escalates instead of
            guessing. This box is the single lever on how much it can handle alone.
          </p>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={() => void save()}
          disabled={saving}
          className="inline-flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-40 transition-colors"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
          Save settings
        </button>
      </div>
    </Section>
  );
}
