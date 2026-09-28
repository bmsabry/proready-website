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
  type SupportAiHealth,
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
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
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
//
// The inbox answers one question: whose move is it? Three trays, newest
// first in each, so a message that just arrived is at the top of "Needs your
// reply" rather than under a stale ticket from last month:
//   Needs your reply     — escalated to you, or triage never finished
//   Waiting on customer  — you replied; their answer brings it back up
//   Answered by AI       — what the assistant handled alone (last 14 days)
// Replying keeps a conversation open (Waiting on customer); closing it is a
// separate, deliberate click.

const FILTERS: { key: string; label: string }[] = [
  { key: 'inbox', label: 'Inbox' },
  { key: 'needs_you', label: 'Needs your reply' },
  { key: 'waiting', label: 'Waiting on customer' },
  { key: 'auto_resolved', label: 'Answered by AI' },
  { key: 'resolved', label: 'Closed' },
  { key: 'archived', label: 'Archived' },
  { key: 'spam', label: 'Spam' },
];

const TRAYS: { key: string; title: string; hint: string; empty: string; tone: string }[] = [
  {
    key: 'needs_you',
    title: 'Needs your reply',
    hint: 'Your move. Each of these already got an automatic “we received your message” reply.',
    empty: 'Nothing needs you right now.',
    tone: 'text-red-300',
  },
  {
    key: 'waiting',
    title: 'Waiting on customer',
    hint: 'You replied — their move. When they answer it comes back up to Needs your reply. Close it once it’s done.',
    empty: 'No conversations waiting on a customer.',
    tone: 'text-amber-300',
  },
  {
    key: 'ai_answered',
    title: 'Answered by AI · last 14 days',
    hint: 'The assistant answered and closed these on its own. Open one to check or correct it.',
    empty: 'The assistant has not answered anything on its own in the last 14 days.',
    tone: 'text-emerald-300',
  },
];

/** "3h", "2d" — how long something has been waiting. */
function ageOf(iso: string | null): string {
  if (!iso) return '';
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

/** Whose move it is, and for how long — the label the inbox is read by. */
function MoveLabel({ t }: { t: SupportTicket }) {
  const pill = (cls: string, text: string, title?: string) => (
    <span
      title={title}
      className={`inline-flex items-center text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${cls}`}
    >
      {text}
    </span>
  );
  if (t.tray === 'needs_you') {
    if (t.status !== 'escalated') {
      return t.stuck
        ? pill(
            'bg-amber-500/15 text-amber-300 border-amber-500/30',
            'Stuck — reply yourself',
            'Automatic triage never finished on this one.',
          )
        : pill('bg-violet-500/15 text-violet-300 border-violet-500/30', 'AI reading…');
    }
    return pill(
      'bg-red-500/15 text-red-300 border-red-500/35',
      `Reply needed · ${ageOf(t.last_customer_message_at ?? t.created_at)}`,
      'Waiting for you since their last message',
    );
  }
  if (t.tray === 'waiting') {
    return t.follow_up
      ? pill(
          'bg-amber-500/15 text-amber-200 border-amber-500/40',
          `No answer ${ageOf(t.last_message_at)} · follow up?`,
          'They have not replied for a few days — nudge them, or close it.',
        )
      : pill(
          'bg-amber-500/10 text-amber-300 border-amber-500/25',
          `Waiting ${ageOf(t.last_message_at)}`,
        );
  }
  return <StatusPill status={t.status} />;
}

function TicketRow({
  t,
  checked,
  onCheck,
  onOpen,
}: {
  t: SupportTicket;
  checked: boolean;
  onCheck: (on: boolean) => void;
  onOpen: () => void;
}) {
  const bold = t.tray === 'needs_you';
  return (
    <div
      className={`flex items-center gap-3 px-3 py-2.5 hover:bg-slate-800/40 transition-colors ${
        bold ? 'bg-slate-900/40' : ''
      }`}
    >
      <input
        type="checkbox"
        aria-label={`Select ticket ${t.ref}`}
        checked={checked}
        onChange={(e) => onCheck(e.target.checked)}
        className="accent-cyan-500 shrink-0"
      />
      <button onClick={onOpen} className="flex-1 min-w-0 text-left">
        <div className="flex items-center gap-2">
          {bold && (
            <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" title="Your move" />
          )}
          <span className={`truncate text-sm ${bold ? 'text-white font-medium' : 'text-slate-200'}`}>
            {t.subject}
          </span>
          <span className="text-[10px] text-slate-600 font-mono shrink-0">#{t.ref}</span>
        </div>
        <div className="text-xs text-slate-500 truncate">
          {t.submitter_name ? `${t.submitter_name} · ` : ''}
          {t.submitter_email}
          {t.summary ? ` — ${t.summary}` : ''}
        </div>
        {/* On a phone the pill columns are hidden; keep whose-move visible. */}
        <div className="sm:hidden mt-1">
          <MoveLabel t={t} />
        </div>
      </button>
      <div className="hidden md:block w-36 shrink-0">
        <PriorityPill priority={t.priority} label={t.category_label} />
      </div>
      <div className="hidden sm:block w-48 shrink-0">
        <MoveLabel t={t} />
      </div>
      <div className="hidden sm:block w-16 text-right text-xs text-slate-500 shrink-0">
        {relative(t.last_message_at)}
      </div>
    </div>
  );
}

/** Red when automatic replies have stopped — the desk keeps acknowledging
 *  customers, so without this an outage is invisible. */
function AiBanner({
  ai,
  onChecked,
  onSettings,
  onAuthError,
}: {
  ai: SupportAiHealth;
  onChecked: () => void;
  onSettings: () => void;
  onAuthError: () => void;
}) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    setChecking(true);
    setResult(null);
    setError(null);
    try {
      const r = await api<{ ok: boolean; error: string }>('/api/admin/support/ai-check', {
        method: 'POST',
      });
      setResult(r.ok ? 'The model answered — automatic replies are back on.' : `Still failing: ${r.error}`);
      onChecked();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setChecking(false);
    }
  }

  if (ai.state !== 'down' && ai.state !== 'off') {
    return result ? <Notice kind="success">{result}</Notice> : null;
  }
  return (
    <div className="mb-4 rounded-lg border border-red-500/40 bg-red-950/30 px-3.5 py-3 text-sm text-red-100">
      <div className="flex items-start gap-2">
        <Bot className="w-4 h-4 mt-0.5 shrink-0 text-red-300" />
        <div className="flex-1 min-w-0 space-y-1">
          <div className="font-semibold text-red-200">Automatic replies are OFF</div>
          <p className="text-red-100/90 break-words">
            {ai.error}.
            {ai.since ? ` Since ${formatDate(ai.since)}` : ''}
            {ai.missed > 0
              ? `${ai.since ? ',' : ''} ${ai.missed} message${ai.missed === 1 ? '' : 's'} got only the standard “we received your message” reply.`
              : ai.since
                ? '.'
                : ''}{' '}
            Customers are still acknowledged, and every new message comes to <strong>Needs your
            reply</strong> until this is fixed.
          </p>
          {result && <p className="text-amber-200">{result}</p>}
          {error && <p className="text-amber-200">{error}</p>}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={() => void check()}
              disabled={checking}
              className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-red-400/40 text-red-100 hover:bg-red-900/40 disabled:opacity-50"
            >
              {checking ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Check again
            </button>
            <button
              onClick={onSettings}
              className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-slate-700 text-slate-200 hover:bg-slate-800/60"
            >
              <Settings2 className="w-3.5 h-3.5" />
              AI settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Inbox_({
  go,
  onAuthError,
}: {
  go: (v: ViewState, opts?: { replace?: boolean }) => void;
  onAuthError: () => void;
}) {
  const [tickets, setTickets] = useState<SupportTicket[] | null>(null);
  const [stats, setStats] = useState<SupportStats | null>(null);
  const [filter, setFilter] = useState('inbox');
  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ limit: '300' });
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
        if (!quiet) setSelected(new Set());
      } catch (e) {
        reportError(e, onAuthError, setError);
      } finally {
        setLoading(false);
      }
    },
    [filter, query, onAuthError],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // New mail arrives while the page is open; keep it current.
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load(true);
    }, 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function bulk(action: 'archive' | 'resolve' | 'spam') {
    const refs = [...selected];
    if (!refs.length) return;
    const verb = action === 'spam' ? 'mark as spam' : action === 'resolve' ? 'close' : action;
    if (!window.confirm(`${verb} ${refs.length} conversation${refs.length === 1 ? '' : 's'}?`)) return;
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
  const grouped = filter === 'inbox' && !query;
  const toggle = (ref: string, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(ref);
    else next.delete(ref);
    setSelected(next);
  };
  const renderRow = (t: SupportTicket) => (
    <TicketRow
      key={t.ref}
      t={t}
      checked={selected.has(t.ref)}
      onCheck={(on) => toggle(t.ref, on)}
      onOpen={() => go({ page: 'support', ref: t.ref })}
    />
  );

  return (
    <div className="space-y-6">
      <Section
        icon={<Inbox className="w-5 h-5 text-cyan-300" />}
        title="Support"
        sub={
          stats
            ? `${stats.needs_you} need${stats.needs_you === 1 ? 's' : ''} your reply · ${stats.waiting} waiting on customers · ${stats.total} all time${
                stats.ai.state === 'ok' ? ' · automatic replies on' : ''
              }`
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

        {stats && (
          <AiBanner
            ai={stats.ai}
            onChecked={() => void load(true)}
            onSettings={() => go({ page: 'ai' })}
            onAuthError={onAuthError}
          />
        )}

        {stats && stats.needs_you > 0 && !grouped && filter !== 'needs_you' && !query && (
          <button
            onClick={() => setFilter('needs_you')}
            className="w-full mb-4 flex items-center gap-2 text-left text-sm px-3 py-2.5 rounded-lg border border-red-500/30 bg-red-950/25 text-red-200 hover:bg-red-950/40 transition-colors"
          >
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>
              <strong>{stats.needs_you}</strong>{' '}
              {stats.needs_you === 1 ? 'conversation needs' : 'conversations need'} your reply →
            </span>
          </button>
        )}

        {/* Filters + search */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {FILTERS.map((f) => {
            const count =
              f.key === 'needs_you'
                ? stats?.needs_you
                : f.key === 'waiting'
                  ? stats?.waiting
                  : f.key === 'inbox'
                    ? undefined
                    : stats?.by_status?.[f.key];
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
                {count ? (
                  <span
                    className={`ml-1.5 ${f.key === 'needs_you' ? 'text-red-300 font-semibold' : 'opacity-70'}`}
                  >
                    {count}
                  </span>
                ) : null}
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
                Close
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
        ) : grouped ? (
          <div className="space-y-5">
            {TRAYS.map((tray) => {
              const items = rows.filter((t) => t.tray === tray.key);
              return (
                <div key={tray.key}>
                  <div className="flex items-baseline gap-2 mb-1">
                    <h3 className={`text-sm font-semibold ${tray.tone}`}>
                      {tray.title}
                      <span className="ml-1.5 text-slate-500 font-normal">{items.length}</span>
                    </h3>
                  </div>
                  <p className="text-[11px] text-slate-500 mb-2">{tray.hint}</p>
                  {items.length === 0 ? (
                    <div className="flex items-center gap-2 text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl px-3 py-3">
                      {tray.key === 'needs_you' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                      {tray.empty}
                    </div>
                  ) : (
                    <div className="border border-slate-800 rounded-xl overflow-hidden divide-y divide-slate-800/70">
                      {items.map(renderRow)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Inbox className="w-6 h-6 text-slate-600" />}
            title={query ? 'Nothing matched that search' : 'Nothing here'}
            hint={
              query
                ? 'Try the ticket ref, or part of the sender’s email address.'
                : 'No conversations in this list.'
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
              <span className="hidden md:block w-36">Category</span>
              <span className="hidden sm:block w-48">Whose move</span>
              <span className="hidden sm:block w-16 text-right">Last</span>
            </div>
            <div className="divide-y divide-slate-800/70">{rows.map(renderRow)}</div>
          </div>
        )}
      </Section>

      {showSettings && (
        <SupportSettingsPanel onAuthError={onAuthError} onOpenAi={() => go({ page: 'ai' })} />
      )}
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
  // Which button is sending: 'open' keeps the conversation (Waiting on
  // customer), 'close' closes it. Keeping it open is the default: a reply is
  // rarely the end of it, and a closed conversation leaves the inbox.
  const [sending, setSending] = useState<'open' | 'close' | null>(null);

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

  async function send(close: boolean) {
    if (!reply.trim()) return;
    setSending(close ? 'close' : 'open');
    setError(null);
    try {
      const res = await api<{ delivered: boolean; status: string; warning: string }>(
        `/api/admin/support/tickets/${encodeURIComponent(ticketRef)}/reply`,
        {
          method: 'POST',
          body: JSON.stringify({
            body_html: rawHtml ? reply : plainTextToEmailHtml(reply),
            set_status: close ? 'resolved' : 'awaiting_customer',
          }),
        },
      );
      if (res.delivered) {
        setReply('');
        setGaps([]);
        flashFor(
          close
            ? 'Reply sent and the conversation closed.'
            : 'Reply sent. It stays under Waiting on customer until they answer or you close it.',
        );
      } else {
        setError(res.warning || 'The email could not be sent.');
      }
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSending(null);
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
                {data.ai_result.source === 'fallback' ? (
                  // The model was down: the "summary" is only the start of the
                  // message shown right below, so say why it came to you.
                  <span className="text-amber-200/90">{data.ai_result.escalation_reason}</span>
                ) : (
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
                )}
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
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <button
                  onClick={() => void send(true)}
                  disabled={sending !== null || !reply.trim()}
                  title="Send, and close the conversation — nothing more to follow up"
                  className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {sending === 'close' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-4 h-4" />
                  )}
                  Send &amp; close
                </button>
                <button
                  onClick={() => void send(false)}
                  disabled={sending !== null || !reply.trim()}
                  title="Send, and keep it under Waiting on customer until they answer"
                  className="inline-flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {sending === 'open' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  Send reply
                </button>
              </div>
            </div>
            <p className="text-[11px] text-slate-600">
              Goes out from info@mail.proreadyengineer.com with ticket #{t.ref} in the subject.
              <strong className="text-slate-500"> Send reply</strong> keeps the conversation under
              Waiting on customer; their answer comes back to Needs your reply (never to the
              automatic assistant). <strong className="text-slate-500">Send &amp; close</strong> is
              for when nothing more is expected.
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
          onClick={() => void onPatch({ status: 'resolved' }, 'Conversation closed.')}
          className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-lg border border-emerald-600/40 text-emerald-300 hover:bg-emerald-950/40 disabled:opacity-40"
        >
          <CheckCircle2 className="w-3.5 h-3.5" />
          Close
        </button>
        <button
          disabled={busy || ticket.status === 'escalated'}
          onClick={() => void onPatch({ status: 'escalated' }, 'Moved to Needs your reply.')}
          className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-lg border border-red-600/40 text-red-300 hover:bg-red-950/40 disabled:opacity-40"
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          Needs my reply
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
  auto_resolved: 'Answered by AI',
  escalated: 'Moved to Needs your reply',
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

function SupportSettingsPanel({
  onAuthError,
  onOpenAi,
}: {
  onAuthError: () => void;
  onOpenAi: () => void;
}) {
  const [s, setS] = useState<SupportSettings | null>(null);
  const [kb, setKb] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<SupportSettings>('/api/admin/support/settings');
      setS(data);
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
        body: JSON.stringify({ kb_text: kb }),
      });
      setS(data);
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
      sub="What the assistant is allowed to tell customers."
    >
      {error && <Notice kind="error">{error}</Notice>}
      {flash && <Notice kind="success">{flash}</Notice>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="space-y-4">
          {/* The model is the website's one AI connection, set and tested in
              AI Settings — shown here so nobody hunts for a second copy. */}
          <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-3 text-sm">
            <div className="text-xs text-slate-500 mb-1">AI model</div>
            {s?.llm_available ? (
              <div className="text-slate-200 break-words">
                {s.model_name} <span className="text-slate-500">via {s.provider}</span>
              </div>
            ) : (
              <div className="text-red-300">
                No AI model is set up, so every message is acknowledged and sent to you.
              </div>
            )}
            <p className="text-[11px] text-slate-500 mt-1.5">
              The same model runs support replies, drafts and the AI Assistant chat.
            </p>
            <button
              onClick={onOpenAi}
              className="mt-2 inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/10"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Change or test it in AI Settings
            </button>
          </div>

          <div className="text-xs text-slate-500 space-y-1.5">
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
          Save
        </button>
      </div>
    </Section>
  );
}
