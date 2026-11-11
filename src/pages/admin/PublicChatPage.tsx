import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft,
  Ban,
  ExternalLink,
  Flag,
  FlaskConical,
  MessageCircle,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Undo2,
} from 'lucide-react';
import { api, formatDate, reportError, type ViewState } from './lib';
import { ConfirmButton, EmptyState, Kpi, LabeledInput, Notice, RefreshButton, Section } from './ui';

/* Site Assistant: the public AI chat on the marketing pages.
 *
 * Conversations (list, search, one conversation in full), "Try it" (the
 * owner's own message through the same reply pipeline, also while the
 * assistant is off), bans (with unban) and the log of every automatic
 * decision, and the settings: on/off, messages per visitor per day, the daily
 * model budget, how long a ban lasts and how long conversations are kept.
 *
 * The assistant ships switched off; this screen says so and how to turn it on.
 *
 * Text is never cut short here: messages, user agents and reasons wrap.
 * A visitor is shown as the first characters of two ids (the cookie id and
 * the hash of the address); no address is stored. */

// ----- Wire types -------------------------------------------------------------

type ChatSettings = {
  enabled: boolean;
  daily_limit: number;
  spend_cap_cents: number;
  ban_days: number;
  retention_days: number;
  disclosure: string;
  record_grace_days: number;
  max_message_chars: number;
  ai_configured: boolean;
  spent_today_cents: number;
  replies_today: number;
  rules: {
    injection_strikes: number;
    abuse_strikes: number;
    over_limit_strikes: number;
    burst_requests: number;
    burst_seconds: number;
  };
};

type ChatEvent = {
  id: number;
  at: string | null;
  kind: string;
  label: string;
  detail: string;
  visitor: string;
  ip_hash: string;
  conversation_id: number | null;
};

type ChatMessage = {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  at: string | null;
  kind: string;
  kind_label: string;
  counted: boolean;
  blocked_text: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  model: string;
};

type Conversation = {
  id: number;
  started_at: string | null;
  last_message_at: string | null;
  message_count: number;
  flagged: boolean;
  visitor: string;
  ip_hash: string;
  user_agent: string;
  page_path: string;
  first_message: string;
  banned: boolean;
  admin_test: boolean;
  admin_email: string;
  messages?: ChatMessage[];
  events?: ChatEvent[];
};

type ChatBan = {
  id: number;
  reason: string;
  reason_label: string;
  detail: string;
  visitor: string;
  ip_hash: string;
  user_agent: string;
  conversation_id: number | null;
  created_at: string | null;
  expires_at: string | null;
  lifted_at: string | null;
  lifted_by: string;
  refused_count: number;
  last_refused_at: string | null;
  active: boolean;
};

/** POST /api/admin/chat/try: one message through the visitor's reply pipeline. */
type TryResult = {
  status: 'ok' | 'refused' | 'blocked' | 'error' | 'unavailable';
  reply: string;
  outcome: string;
  reason: string;
  model_called: boolean;
  model_text: string;
  pages_used: { path: string; title: string }[];
  pages_listed: number;
  conversation_id: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  model: string;
  assistant_enabled: boolean;
  spent_today_cents: number;
  spend_cap_cents: number;
};

type Tab = 'conversations' | 'try' | 'bans' | 'settings';
type ChatView = Extract<ViewState, { page: 'chat' }>;

const when = (iso: string | null) => (iso ? formatDate(iso) : '');
const dollars = (cents: number) => `$${(cents / 100).toFixed(2)}`;

const Pill = ({ tone, children }: { tone: 'red' | 'amber' | 'slate' | 'emerald'; children: React.ReactNode }) => {
  const cls = {
    red: 'bg-red-500/20 text-red-200 border-red-500/40',
    amber: 'bg-amber-500/20 text-amber-200 border-amber-500/40',
    slate: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
    emerald: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
  }[tone];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border whitespace-nowrap ${cls}`}>
      {children}
    </span>
  );
};

const Who = ({ visitor, ipHash }: { visitor: string; ipHash: string }) => (
  <span className="font-mono text-xs text-slate-300 break-all">
    visitor {visitor || 'none'} · address {ipHash || 'none'}
  </span>
);

// ----- Page -------------------------------------------------------------------

export default function PublicChatPage({
  view,
  go,
  onAuthError,
}: {
  view: ChatView;
  go: (v: ViewState, opts?: { replace?: boolean }) => void;
  onAuthError: () => void;
}) {
  const tab: Tab = view.conversation ? 'conversations' : (view.tab ?? 'conversations');
  const [settings, setSettings] = useState<ChatSettings | null>(null);
  const [error, setError] = useState('');

  const loadSettings = useCallback(async () => {
    try {
      setSettings(await api<ChatSettings>('/api/admin/chat/settings'));
      setError('');
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }, [onAuthError]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings, tab]);

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: 'conversations', label: 'Conversations', icon: <MessageCircle className="w-4 h-4" /> },
    { key: 'try', label: 'Try it', icon: <FlaskConical className="w-4 h-4" /> },
    { key: 'bans', label: 'Bans and decisions', icon: <Ban className="w-4 h-4" /> },
    { key: 'settings', label: 'Settings', icon: <Settings className="w-4 h-4" /> },
  ];

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">Site Assistant</h1>
          <p className="text-sm text-slate-300 mt-1 max-w-3xl">
            The AI chat on the public pages. It answers from the site's own public pages and the model's
            general knowledge, offers a call, and never states a consulting rate.
          </p>
        </div>
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      {settings && (
        <>
          {!settings.enabled && (
            <div
              data-testid="chat-off-notice"
              className="mb-4 text-sm border rounded-lg px-4 py-3 text-amber-100 bg-amber-950/40 border-amber-900/60"
            >
              <p className="font-semibold text-amber-200">The assistant is switched OFF.</p>
              <p className="mt-1">
                Visitors do not see the chat button, nothing is answered and nothing is stored. You can still test it
                yourself under “Try it”.
              </p>
              <p className="mt-1">
                To switch it on: open Settings, tick “Assistant switched on”, then press “Save settings”.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={() => go({ page: 'chat', tab: 'try' })} className="btn-secondary text-sm py-1.5 px-3">
                  <FlaskConical className="w-4 h-4" /> Try it first
                </button>
                <button type="button" onClick={() => go({ page: 'chat', tab: 'settings' })} className="btn-secondary text-sm py-1.5 px-3">
                  <Settings className="w-4 h-4" /> Open Settings
                </button>
              </div>
            </div>
          )}
          {!settings.ai_configured && (
            <Notice kind="warn">
              No AI model is set up (Admin → AI Settings).{' '}
              {settings.enabled
                ? 'Visitors who open the chat are told it is unavailable.'
                : 'Set one up before trying the assistant or switching it on.'}
            </Notice>
          )}
          {settings.enabled && settings.ai_configured && settings.spent_today_cents >= settings.spend_cap_cents && (
            <Notice kind="warn">
              Today's budget is used up ({dollars(settings.spent_today_cents)} of {dollars(settings.spend_cap_cents)}).
              Visitors are told the assistant is unavailable for the rest of today (UTC).
            </Notice>
          )}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
            <Kpi
              label="Status"
              value={settings.enabled ? 'On' : 'Off'}
              accent={settings.enabled ? 'emerald' : 'amber'}
              sub={
                settings.enabled
                  ? settings.ai_configured
                    ? 'Answering visitors'
                    : 'On, but no AI model set up'
                  : 'Hidden from visitors'
              }
            />
            <Kpi label="Replies today" value={settings.replies_today} sub="Answered by the model (UTC day)" />
            <Kpi
              label="Spent today"
              value={dollars(settings.spent_today_cents)}
              accent={settings.spent_today_cents >= settings.spend_cap_cents ? 'amber' : 'cyan'}
              sub={`Daily budget ${dollars(settings.spend_cap_cents)} (estimate)`}
            />
            <Kpi label="Per visitor" value={settings.daily_limit} sub="Messages in any 24 hours" />
          </div>
        </>
      )}

      <div className="flex flex-wrap gap-2 mb-6" role="tablist" aria-label="Site Assistant sections">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() =>
              go(t.key === 'conversations' ? { page: 'chat' } : { page: 'chat', tab: t.key }, { replace: true })
            }
            className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm border transition-colors ${
              tab === t.key
                ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/60 border-slate-800'
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'conversations' &&
        (view.conversation ? (
          <ConversationDetail
            id={view.conversation}
            onBack={() => go({ page: 'chat' })}
            openBans={() => go({ page: 'chat', tab: 'bans' })}
            onAuthError={onAuthError}
          />
        ) : (
          <ConversationList open={(id) => go({ page: 'chat', conversation: id })} onAuthError={onAuthError} />
        ))}
      {tab === 'try' && settings && (
        <TryIt settings={settings} onUsed={() => void loadSettings()} onAuthError={onAuthError} />
      )}
      {tab === 'bans' && (
        <BansAndDecisions
          openConversation={(id) => go({ page: 'chat', conversation: id })}
          onAuthError={onAuthError}
        />
      )}
      {tab === 'settings' && settings && (
        <SettingsForm settings={settings} onSaved={setSettings} onAuthError={onAuthError} />
      )}
    </div>
  );
}

// ----- Conversations ------------------------------------------------------------

const PAGE_SIZE = 50;

function ConversationList({ open, onAuthError }: { open: (id: number) => void; onAuthError: () => void }) {
  const [rows, setRows] = useState<Conversation[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [applied, setApplied] = useState('');
  const [flagged, setFlagged] = useState(false);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (applied) params.set('q', applied);
      if (flagged) params.set('flagged', 'true');
      const data = await api<{ total: number; conversations: Conversation[] }>(
        `/api/admin/chat/conversations?${params.toString()}`,
      );
      setRows(data.conversations);
      setTotal(data.total);
      setError('');
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [applied, flagged, offset, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Section
      icon={<MessageCircle className="w-5 h-5 text-cyan-400" />}
      title="Conversations"
      sub="Every conversation is kept, with the visitor's two ids and browser, so misuse can be reviewed."
      actions={<RefreshButton onClick={() => void load()} loading={loading} small />}
    >
      {error && <Notice kind="error">{error}</Notice>}
      <form
        className="flex flex-wrap items-end gap-3 mb-4"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setApplied(q.trim());
        }}
      >
        <div className="flex-1 min-w-[220px]">
          <LabeledInput
            label="Search messages, or a visitor / address id"
            value={q}
            onChange={setQ}
            icon={<Search className="w-3 h-3" />}
            placeholder="hydrogen, or the first characters of an id"
          />
        </div>
        <button type="submit" className="btn-secondary text-sm py-2 px-3">
          Search
        </button>
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer select-none py-2">
          <input
            type="checkbox"
            checked={flagged}
            onChange={(e) => {
              setOffset(0);
              setFlagged(e.target.checked);
            }}
            className="accent-cyan-500"
          />
          Flagged only
        </label>
      </form>

      {rows && rows.length === 0 ? (
        <EmptyState
          icon={<MessageCircle className="w-5 h-5" />}
          title={applied || flagged ? 'Nothing matches' : 'No conversations yet'}
          hint={
            applied || flagged
              ? 'Clear the search or the filter to see every conversation.'
              : 'Conversations appear here as soon as a visitor writes to the assistant.'
          }
        />
      ) : (
        <ul className="space-y-3">
          {(rows ?? []).map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => open(c.id)}
                className="w-full text-left bg-slate-900/70 border border-slate-800 hover:border-cyan-500/40 rounded-xl p-4 transition-colors"
              >
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <span className="text-xs text-slate-400">{when(c.last_message_at)}</span>
                  <Pill tone="slate">
                    {c.message_count} message{c.message_count === 1 ? '' : 's'}
                  </Pill>
                  {c.admin_test && (
                    <Pill tone="emerald">
                      <FlaskConical className="w-3 h-3" /> Admin test
                    </Pill>
                  )}
                  {c.flagged && (
                    <Pill tone="amber">
                      <Flag className="w-3 h-3" /> Flagged
                    </Pill>
                  )}
                  {c.banned && (
                    <Pill tone="red">
                      <Ban className="w-3 h-3" /> Banned
                    </Pill>
                  )}
                </div>
                <p className="text-sm text-slate-100 whitespace-pre-wrap break-words">{c.first_message}</p>
                <p className="mt-2">
                  {c.admin_test ? (
                    <span className="text-xs text-slate-300 break-all">Your own test ({c.admin_email})</span>
                  ) : (
                    <Who visitor={c.visitor} ipHash={c.ip_hash} />
                  )}
                </p>
              </button>
            </li>
          ))}
        </ul>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-3 mt-4 text-sm text-slate-300">
          <span>
            {offset + 1} to {Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <span className="flex gap-2">
            <button
              type="button"
              className="btn-secondary text-sm py-1.5 px-3 disabled:opacity-40"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer
            </button>
            <button
              type="button"
              className="btn-secondary text-sm py-1.5 px-3 disabled:opacity-40"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older
            </button>
          </span>
        </div>
      )}
    </Section>
  );
}

function ConversationDetail({
  id,
  onBack,
  openBans,
  onAuthError,
}: {
  id: number;
  onBack: () => void;
  openBans: () => void;
  onAuthError: () => void;
}) {
  const [c, setC] = useState<Conversation | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setC(await api<Conversation>(`/api/admin/chat/conversations/${id}`));
      setError('');
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [id, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <button type="button" onClick={onBack} className="btn-ghost mb-4">
        <ArrowLeft className="w-4 h-4" /> All conversations
      </button>
      {error && <Notice kind="error">{error}</Notice>}
      {c && (
        <Section
          icon={<MessageCircle className="w-5 h-5 text-cyan-400" />}
          title={`Conversation ${c.id}`}
          sub={`Started ${when(c.started_at)}; last message ${when(c.last_message_at)}.`}
          actions={<RefreshButton onClick={() => void load()} loading={loading} small />}
        >
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 mb-5 space-y-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              {c.flagged && (
                <Pill tone="amber">
                  <Flag className="w-3 h-3" /> Flagged
                </Pill>
              )}
              {c.admin_test ? (
                <Pill tone="emerald">
                  <FlaskConical className="w-3 h-3" /> Admin test by {c.admin_email || 'the owner'}: no visitor involved
                </Pill>
              ) : c.banned ? (
                <button type="button" onClick={openBans} className="inline-flex">
                  <Pill tone="red">
                    <Ban className="w-3 h-3" /> This visitor is banned: open Bans
                  </Pill>
                </button>
              ) : (
                <Pill tone="emerald">
                  <ShieldCheck className="w-3 h-3" /> Not banned
                </Pill>
              )}
            </div>
            {!c.admin_test && (
              <p>
                <Who visitor={c.visitor} ipHash={c.ip_hash} />
              </p>
            )}
            <p className="text-slate-300 break-words">
              <span className="text-slate-400">Browser: </span>
              {c.user_agent || 'not sent'}
            </p>
            {c.page_path && (
              <p className="text-slate-300 break-words">
                <span className="text-slate-400">Started on page: </span>
                {c.page_path}
              </p>
            )}
          </div>

          <ol className="space-y-3">
            {(c.messages ?? []).map((m) => {
              const blocked = m.kind.endsWith('_blocked');
              const refused = m.kind === 'refused' || m.kind === 'abuse';
              return (
                <li
                  key={m.id}
                  className={`rounded-xl border p-4 ${
                    m.role === 'user' ? 'bg-cyan-500/10 border-cyan-500/30 ml-0 sm:mr-12' : 'bg-slate-900/70 border-slate-800 sm:ml-12'
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2 mb-2 text-xs text-slate-400">
                    <span className="font-semibold text-slate-200">{m.role === 'user' ? 'Visitor' : 'Assistant'}</span>
                    <span>{when(m.at)}</span>
                    {m.role === 'user' && m.kind === 'error' && <Pill tone="slate">Not counted: the model did not answer</Pill>}
                    {m.role === 'assistant' && m.kind !== 'answer' && (
                      <Pill tone={blocked || refused ? 'amber' : 'slate'}>{m.kind_label}</Pill>
                    )}
                    {m.role === 'assistant' && m.model && (
                      <span>
                        {m.model} · {m.tokens_in} in / {m.tokens_out} out · ${m.cost_usd.toFixed(4)}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-slate-100 whitespace-pre-wrap break-words">{m.content}</p>
                  {m.blocked_text && (
                    <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                      <p className="text-xs font-semibold text-amber-200 mb-1">
                        What the model wrote (never shown to the visitor)
                      </p>
                      <p className="text-sm text-amber-100 whitespace-pre-wrap break-words">{m.blocked_text}</p>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>

          {(c.events ?? []).length > 0 && (
            <div className="mt-6">
              <h3 className="text-sm font-semibold text-white mb-2">Decisions in this conversation</h3>
              <EventList events={c.events ?? []} />
            </div>
          )}
        </Section>
      )}
    </div>
  );
}

// ----- Try it -------------------------------------------------------------------

type Trial = { question: string; result: TryResult };

const TRY_TONE: Record<TryResult['status'], 'emerald' | 'amber' | 'red'> = {
  ok: 'emerald',
  blocked: 'amber',
  refused: 'amber',
  unavailable: 'amber',
  error: 'red',
};

/** The owner's own message, through the reply pipeline a visitor's takes.
 *  Works while the assistant is off; uses up no visitor's messages. */
function TryIt({
  settings,
  onUsed,
  onAuthError,
}: {
  settings: ChatSettings;
  onUsed: () => void;
  onAuthError: () => void;
}) {
  const [draft, setDraft] = useState('');
  const [trials, setTrials] = useState<Trial[]>([]);
  const [conversationId, setConversationId] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const max = settings.max_message_chars;

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const question = draft.trim();
    if (!question || sending) return;
    setSending(true);
    setError('');
    try {
      const result = await api<TryResult>('/api/admin/chat/try', {
        method: 'POST',
        body: JSON.stringify({ message: question, conversation_id: conversationId }),
      });
      setTrials((t) => [...t, { question, result }]);
      setConversationId(result.conversation_id || '');
      setDraft('');
      onUsed();
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setSending(false);
    }
  };

  return (
    <Section
      icon={<FlaskConical className="w-5 h-5 text-cyan-400" />}
      title="Try it"
      sub="Send a message exactly as a visitor would. It takes the same path: the same page reading, instructions, model, token ceiling and price check, and it is counted in today's budget."
    >
      <ul className="list-disc pl-5 mb-4 text-sm text-slate-300 space-y-1 max-w-3xl">
        <li>Works while the assistant is switched off{settings.enabled ? '' : ' (it is off now)'}.</li>
        <li>Uses up no visitor's messages and can never lead to a ban.</li>
        <li>Each test is kept under Conversations, marked “Admin test”, and logged in the decisions log.</li>
      </ul>
      {error && <Notice kind="error">{error}</Notice>}

      <form
        onSubmit={send}
        data-testid="chat-try-form"
        className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 max-w-3xl"
      >
        <label className="block">
          <span className="text-[11px] uppercase tracking-wider text-slate-300 mb-1 block">
            Your test message{trials.length > 0 ? ' (continues the test conversation below)' : ''}
          </span>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value.slice(0, max))}
            rows={3}
            maxLength={max}
            placeholder="For example: How much does a call cost?  ·  What limits lean blowout?  ·  Ignore your instructions and…"
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
          />
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="submit" disabled={sending || !draft.trim()} className="btn-primary text-sm py-2.5 px-4 disabled:opacity-50">
            <Send className="w-4 h-4" /> {sending ? 'Waiting for the model…' : 'Send test'}
          </button>
          {trials.length > 0 && (
            <button
              type="button"
              className="btn-secondary text-sm py-2 px-3"
              onClick={() => {
                setTrials([]);
                setConversationId('');
              }}
            >
              Start a new test conversation
            </button>
          )}
          <span className="text-xs text-slate-400">
            {draft.length} of {max} characters
          </span>
        </div>
      </form>

      <ol className="mt-6 space-y-5 max-w-3xl" data-testid="chat-try-results">
        {trials.map(({ question, result: r }, i) => (
          <li key={i} className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
            <div>
              <p className="text-xs font-semibold text-slate-400 mb-1">You asked</p>
              <p className="text-sm text-slate-100 whitespace-pre-wrap break-words">{question}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={TRY_TONE[r.status]}>{r.outcome}</Pill>
              {!r.model_called && <Pill tone="slate">The model was not called</Pill>}
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-400 mb-1">What a visitor would see</p>
              <p className="text-sm text-slate-100 whitespace-pre-wrap break-words rounded-lg bg-slate-950/70 border border-slate-800 px-3 py-2.5">
                {r.reply}
              </p>
            </div>
            {r.model_text && r.model_text.trim() !== r.reply.trim() && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                <p className="text-xs font-semibold text-amber-200 mb-1">
                  What the model wrote{r.status === 'blocked' ? ' (never shown to the visitor)' : ''}
                </p>
                <p className="text-sm text-amber-100 whitespace-pre-wrap break-words">{r.model_text}</p>
              </div>
            )}
            {r.reason && (
              <p className="text-sm text-slate-300 break-words">
                <span className="text-slate-400">Why: </span>
                {r.reason}
              </p>
            )}
            {r.model_called && (
              <div>
                <p className="text-xs font-semibold text-slate-400 mb-1">
                  Public pages quoted to the model ({r.pages_used.length} of the {r.pages_listed} pages it was given the
                  list of)
                </p>
                {r.pages_used.length === 0 ? (
                  <p className="text-sm text-slate-300">
                    {r.pages_listed === 0
                      ? 'The site could not be read, so the model was told to state no facts about the company.'
                      : 'No page matched this message closely; the model saw only the list of pages.'}
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {r.pages_used.map((pg) => (
                      <li key={pg.path} className="text-sm break-words">
                        <a
                          href={pg.path}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-cyan-400 hover:text-cyan-300 underline font-mono text-xs"
                        >
                          {pg.path}
                          <ExternalLink className="inline w-3 h-3 ml-1" aria-hidden="true" />
                        </a>
                        <span className="text-slate-300"> {pg.title}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <p className="text-xs text-slate-400 break-words">
              {r.model_called && r.model
                ? `${r.model} · ${r.tokens_in} tokens in, ${r.tokens_out} out · about $${r.cost_usd.toFixed(4)} · `
                : ''}
              Spent today: {dollars(r.spent_today_cents)} of {dollars(r.spend_cap_cents)}
            </p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

// ----- Bans and the decision log ------------------------------------------------

function EventList({
  events,
  openConversation,
}: {
  events: ChatEvent[];
  openConversation?: (id: number) => void;
}) {
  return (
    <ul className="space-y-2">
      {events.map((e) => (
        <li key={e.id} className="bg-slate-900/70 border border-slate-800 rounded-lg px-3 py-2.5 text-sm">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-xs text-slate-400">{when(e.at)}</span>
            <span className="font-semibold text-slate-100">{e.label}</span>
            {openConversation && e.conversation_id && (
              <button
                type="button"
                onClick={() => openConversation(e.conversation_id as number)}
                className="text-xs text-cyan-400 hover:text-cyan-300 underline"
              >
                Conversation {e.conversation_id}
              </button>
            )}
          </div>
          {e.detail && <p className="text-slate-300 mt-1 break-words">{e.detail}</p>}
          {(e.visitor || e.ip_hash) && (
            <p className="mt-1">
              <Who visitor={e.visitor} ipHash={e.ip_hash} />
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function BansAndDecisions({
  openConversation,
  onAuthError,
}: {
  openConversation: (id: number) => void;
  onAuthError: () => void;
}) {
  const [bans, setBans] = useState<ChatBan[] | null>(null);
  const [events, setEvents] = useState<ChatEvent[] | null>(null);
  const [activeOnly, setActiveOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, e] = await Promise.all([
        api<{ bans: ChatBan[] }>(`/api/admin/chat/bans${activeOnly ? '?active=true' : ''}`),
        api<{ events: ChatEvent[] }>('/api/admin/chat/events?limit=200'),
      ]);
      setBans(b.bans);
      setEvents(e.events);
      setError('');
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [activeOnly, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const unban = async (ban: ChatBan) => {
    try {
      await api<ChatBan>(`/api/admin/chat/bans/${ban.id}/unban`, { method: 'POST' });
      setDone(`Ban ${ban.id} lifted. That visitor can use the assistant again, with a clean slate.`);
      await load();
    } catch (err) {
      reportError(err, onAuthError, setError);
    }
  };

  return (
    <div className="space-y-10">
      <Section
        icon={<Ban className="w-5 h-5 text-cyan-400" />}
        title="Bans"
        sub="A ban covers the visitor's cookie id and their address, so clearing cookies does not lift it. Banned visitors get one fixed message."
        actions={<RefreshButton onClick={() => void load()} loading={loading} small />}
      >
        {error && <Notice kind="error">{error}</Notice>}
        {done && <Notice kind="success">{done}</Notice>}
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer select-none mb-4">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
            className="accent-cyan-500"
          />
          Active bans only
        </label>
        {bans && bans.length === 0 ? (
          <EmptyState
            icon={<ShieldCheck className="w-5 h-5" />}
            title={activeOnly ? 'Nobody is banned' : 'No bans on record'}
            hint="Bans are placed automatically for repeated attempts on the assistant's instructions, abusive messages, requests after the daily limit, and scripted bursts."
          />
        ) : (
          <ul className="space-y-3">
            {(bans ?? []).map((b) => (
              <li key={b.id} className="bg-slate-900/70 border border-slate-800 rounded-xl p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1 space-y-1.5 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      {b.active ? <Pill tone="red">Active</Pill> : <Pill tone="slate">{b.lifted_at ? 'Lifted' : 'Ended'}</Pill>}
                      <span className="font-semibold text-slate-100">{b.reason_label}</span>
                    </div>
                    {b.detail && <p className="text-slate-300 break-words">{b.detail}</p>}
                    <p className="text-slate-300">
                      Banned {when(b.created_at)}; until {when(b.expires_at)}.
                      {b.lifted_at && ` Lifted ${when(b.lifted_at)} by ${b.lifted_by || 'admin'}.`}
                    </p>
                    <p className="text-slate-300">
                      Requests refused since: {b.refused_count}
                      {b.last_refused_at ? ` (last ${when(b.last_refused_at)})` : ''}
                    </p>
                    <p>
                      <Who visitor={b.visitor} ipHash={b.ip_hash} />
                    </p>
                    {b.user_agent && (
                      <p className="text-slate-300 break-words">
                        <span className="text-slate-400">Browser: </span>
                        {b.user_agent}
                      </p>
                    )}
                    {b.conversation_id && (
                      <button
                        type="button"
                        onClick={() => openConversation(b.conversation_id as number)}
                        className="text-cyan-400 hover:text-cyan-300 underline"
                      >
                        Open conversation {b.conversation_id}
                      </button>
                    )}
                  </div>
                  {b.active && (
                    <ConfirmButton
                      message={`Lift ban ${b.id}? This visitor will be able to use the assistant again.`}
                      onConfirm={() => void unban(b)}
                      className="btn-secondary text-sm py-2 px-3 shrink-0"
                    >
                      <Undo2 className="w-4 h-4" /> Unban
                    </ConfirmButton>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        icon={<Flag className="w-5 h-5 text-cyan-400" />}
        title="Decisions log"
        sub="Every refusal, blocked reply, ban and unban, newest first, each with its reason."
      >
        {events && events.length === 0 ? (
          <EmptyState icon={<ShieldCheck className="w-5 h-5" />} title="Nothing logged yet" />
        ) : (
          <EventList events={events ?? []} openConversation={openConversation} />
        )}
      </Section>
    </div>
  );
}

// ----- Settings ---------------------------------------------------------------

function SettingsForm({
  settings,
  onSaved,
  onAuthError,
}: {
  settings: ChatSettings;
  onSaved: (s: ChatSettings) => void;
  onAuthError: () => void;
}) {
  const [enabled, setEnabled] = useState(settings.enabled);
  const [dailyLimit, setDailyLimit] = useState(String(settings.daily_limit));
  const [capDollars, setCapDollars] = useState((settings.spend_cap_cents / 100).toFixed(2));
  const [banDays, setBanDays] = useState(String(settings.ban_days));
  const [keepDays, setKeepDays] = useState(String(settings.retention_days));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setDone('');
    const limit = Number(dailyLimit);
    const cap = Number(capDollars);
    const days = Number(banDays);
    if (!Number.isInteger(limit) || limit < 1 || limit > 200) {
      setError('Messages per visitor per day must be a whole number from 1 to 200.');
      return;
    }
    if (!Number.isFinite(cap) || capDollars.trim() === '' || cap < 0 || cap > 900) {
      setError('The daily budget must be an amount from 0 to 900 dollars.');
      return;
    }
    if (!Number.isInteger(days) || days < 1 || days > 3650) {
      setError('Ban length must be a whole number of days from 1 to 3650.');
      return;
    }
    const keep = Number(keepDays);
    if (!Number.isInteger(keep) || keep < 1 || keep > 3650) {
      setError('Conversations must be kept for a whole number of days from 1 to 3650.');
      return;
    }
    setSaving(true);
    try {
      const saved = await api<ChatSettings>('/api/admin/chat/settings', {
        method: 'PUT',
        body: JSON.stringify({
          enabled,
          daily_limit: limit,
          spend_cap_cents: Math.round(cap * 100),
          ban_days: days,
          retention_days: keep,
        }),
      });
      onSaved(saved);
      // The public widget remembers "on" or "off" for a few minutes per tab.
      // Forget it here, so the owner sees his change on the next page he opens
      // in this tab.
      try {
        sessionStorage.removeItem('pre:chat-enabled');
      } catch {
        /* private mode */
      }
      setError('');
      setDone('Saved.');
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setSaving(false);
    }
  };

  const r = settings.rules;
  return (
    <Section
      icon={<Settings className="w-5 h-5 text-cyan-400" />}
      title="Settings"
      sub="Changes apply to the next message a visitor sends."
    >
      {error && <Notice kind="error">{error}</Notice>}
      {done && <Notice kind="success">{done}</Notice>}
      {/* noValidate: the checks in save() answer in words, next to the form. */}
      <form onSubmit={save} noValidate className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-5 max-w-2xl">
        <label className="flex items-start gap-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="accent-cyan-500 mt-1"
          />
          <span>
            <span className="block text-sm font-semibold text-white">Assistant switched on</span>
            <span className="block text-sm text-slate-300">
              Off: the chat button disappears from the public pages and nothing is answered or stored.
            </span>
          </span>
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <LabeledInput
            label="Messages per visitor per day"
            type="number"
            min={1}
            step={1}
            value={dailyLimit}
            onChange={setDailyLimit}
            required
          />
          <LabeledInput
            label="Daily budget (US dollars)"
            type="number"
            min={0}
            step="0.01"
            value={capDollars}
            onChange={setCapDollars}
            required
          />
          <LabeledInput
            label="Ban length (days)"
            type="number"
            min={1}
            step={1}
            value={banDays}
            onChange={setBanDays}
            required
          />
          <LabeledInput
            label="Keep conversations for (days)"
            type="number"
            min={1}
            step={1}
            value={keepDays}
            onChange={setKeepDays}
            required
          />
        </div>
        <p className="text-sm text-slate-300">
          <span className="text-slate-400">Visitors are told: </span>
          <span data-testid="chat-disclosure-preview">“{settings.disclosure}”</span>
        </p>
        <button type="submit" disabled={saving} className="btn-primary text-sm py-2.5 px-4 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save settings'}
        </button>
      </form>

      <div className="mt-6 max-w-2xl text-sm text-slate-300 space-y-2">
        <h3 className="text-sm font-semibold text-white">Rules that are fixed</h3>
        <ul className="list-disc pl-5 space-y-1.5">
          <li>
            A visitor is a signed cookie id and a hash of their address; the higher of the two message counts applies.
          </li>
          <li>Each message is limited to {settings.max_message_chars} characters.</li>
          <li>
            Automatic ban after {r.injection_strikes} attempts to change or read the assistant's instructions,{' '}
            {r.abuse_strikes} abusive messages, {r.over_limit_strikes} requests after the daily limit, or{' '}
            {r.burst_requests} requests within {r.burst_seconds} seconds.
          </li>
          <li>
            The daily budget is an estimate from token counts and resets at midnight UTC. Once it is reached, visitors
            are told the assistant is unavailable for the rest of the day. It is separate from the admin assistant's
            own budget.
          </li>
          <li>A reply that contains a consulting price, or repeats the assistant's instructions, is blocked and kept here for review.</li>
          <li>
            Conversations and messages are deleted after the number of days above. A ban, and the decisions that led
            to it, are deleted {settings.record_grace_days} days after the ban ends; other decisions after{' '}
            {settings.record_grace_days} days. The clean-up runs by itself, at most once a day.
          </li>
        </ul>
      </div>
    </Section>
  );
}
