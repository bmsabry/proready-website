import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ArrowRight, CalendarClock, Send, Sparkles, X } from 'lucide-react';
import { ChatError, chatApi, type ChatStatus, type ChatStatusOut } from '../../lib/chatApi';
import { CONSULT_PUBLIC } from '../../lib/features';

/* The conversation panel of the public AI assistant.
 *
 * A dialog that does not take over the page: the visitor can keep reading
 * and scrolling behind it. Opening it moves the keyboard to the message box,
 * Escape closes it, and replies are announced to screen readers as they
 * arrive.
 *
 * Every refusal (daily limit, ban, unavailable, switched off) is a sentence
 * the server sends; this file words none of them and never mentions a price.
 */

/* The server sends the disclosure with the real retention period in it
   ("... stored for up to 90 days ..."). This wording is only what shows for
   the instant before the first answer from the server, and names no number
   it cannot know. */
const DISCLOSURE_FALLBACK =
  'AI assistant. Answers can be wrong. Messages are stored for a limited time to prevent misuse.';
const GREETING =
  'Hello. I am ProReadyEngineer’s AI assistant. Ask me about gas turbine combustion, test facilities, industrial AI, or what we offer.';
const STORE_KEY = 'pre:chat-thread';

type Bubble = { role: 'user' | 'assistant'; text: string; tone?: 'notice' };
type Thread = { conversationId: string; bubbles: Bubble[] };

const loadThread = (): Thread => {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    if (raw) {
      const t = JSON.parse(raw) as Thread;
      if (Array.isArray(t.bubbles)) return { conversationId: t.conversationId || '', bubbles: t.bubbles.slice(-40) };
    }
  } catch {
    /* start fresh */
  }
  return { conversationId: '', bubbles: [] };
};

const saveThread = (t: Thread) => {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify({ ...t, bubbles: t.bubbles.slice(-40) }));
  } catch {
    /* private mode */
  }
};

/* Site sections a reply may link to. Anything else stays plain text. */
const LINKABLE = /^\/(consult|contact|training|services|insights|case-studies|products|testimonials|about)(\/[a-z0-9-]+)*$/;
const TOKEN = /(https?:\/\/[^\s)]+|\/[a-z][a-z0-9-]*(?:\/[a-z0-9-]+)*)/g;

/** Plain text with the site's own paths (and full links) made clickable. */
const RichText = ({ text, onNavigate }: { text: string; onNavigate: () => void }) => {
  const parts = text.split(TOKEN);
  return (
    <>
      {parts.map((part, i) => {
        if (i % 2 === 0) return <React.Fragment key={i}>{part}</React.Fragment>;
        const before = parts[i - 1] ?? '';
        // "kg/s", "and/or": a slash inside a word is not a link.
        const glued = /[A-Za-z0-9]$/.test(before);
        if (!glued && LINKABLE.test(part)) {
          return (
            <Link key={i} to={part} onClick={onNavigate} className="text-cyan-400 underline hover:text-cyan-300">
              {part}
            </Link>
          );
        }
        if (!glued && /^https:\/\/(www\.)?proreadyengineer\.com(\/|$)/.test(part)) {
          const trimmed = part.replace(/[.,;:!?]+$/, '');
          return (
            <React.Fragment key={i}>
              <a href={trimmed} className="text-cyan-400 underline hover:text-cyan-300 break-all">
                {trimmed}
              </a>
              {part.slice(trimmed.length)}
            </React.Fragment>
          );
        }
        return <React.Fragment key={i}>{part}</React.Fragment>;
      })}
    </>
  );
};

/** Statuses in which the visitor cannot write (until tomorrow, or at all). */
const CLOSED: ChatStatus[] = ['limit', 'banned', 'unavailable', 'disabled'];

export default function ChatPanel({
  open,
  onClose,
  initialStatus,
  initialDisclosure,
  onDisabled,
}: {
  open: boolean;
  onClose: () => void;
  initialStatus: ChatStatusOut | null;
  /** The disclosure as last sent by the server ('' if not known yet). */
  initialDisclosure: string;
  onDisabled: () => void;
}) {
  const { pathname } = useLocation();
  const titleId = useId();
  const noteId = useId();
  const [thread, setThread] = useState<Thread>(() => loadThread());
  const [status, setStatus] = useState<ChatStatusOut | null>(initialStatus);
  const [loadError, setLoadError] = useState('');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const disclosure = status?.disclosure || initialDisclosure || DISCLOSURE_FALLBACK;
  const maxChars = status?.max_chars ?? 800;
  // The last allowed message has been answered: stop here rather than let
  // the visitor send one the server will refuse.
  const usedUp = status?.status === 'ok' && status.remaining <= 0;
  const closed = status ? CLOSED.includes(status.status) || usedUp : false;

  // A fresh status every time the panel opens: the count may have changed in
  // another tab, and the assistant may have been switched off.
  const refresh = useCallback(async () => {
    try {
      const s = await chatApi.status();
      setStatus(s);
      setLoadError('');
      if (!s.enabled) onDisabled();
    } catch (e) {
      setLoadError(e instanceof ChatError ? e.message : 'Could not reach the assistant.');
    }
  }, [onDisabled]);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => {
      if (inputRef.current && !inputRef.current.disabled) inputRef.current.focus();
      else panelRef.current?.focus();
    }, 30);
    return () => window.clearTimeout(id);
  }, [open, closed]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Keep the newest message in view.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [thread.bubbles.length, sending, open, status?.status]);

  useEffect(() => {
    saveThread(thread);
  }, [thread]);

  const send = async () => {
    const text = draft.trim();
    if (!text || sending || closed) return;
    setSending(true);
    setSendError('');
    setDraft('');
    setThread((t) => ({ ...t, bubbles: [...t.bubbles, { role: 'user', text }] }));
    try {
      const r = await chatApi.send(text, thread.conversationId, pathname);
      setThread((t) => ({
        conversationId: r.conversation_id || t.conversationId,
        bubbles: [
          ...t.bubbles,
          { role: 'assistant', text: r.reply, tone: r.status === 'ok' ? undefined : 'notice' },
        ],
      }));
      setStatus((s) => ({
        enabled: r.status !== 'disabled',
        // "error" is for this one message; the assistant itself is still open.
        status: r.status === 'error' ? (s?.status ?? 'ok') : r.status,
        remaining: r.remaining,
        limit: r.limit,
        max_chars: s?.max_chars ?? 800,
        disclosure: s?.disclosure ?? initialDisclosure,
        book_url: r.book_url || '/consult',
        message: r.status === 'ok' || r.status === 'error' ? '' : r.reply,
      }));
      if (r.status === 'error') setDraft(text); // it did not count: give the words back
      if (r.status === 'disabled') onDisabled();
      // That was the last message of the day: fetch the server's own sentence.
      if (r.status === 'ok' && r.remaining <= 0) void refresh();
    } catch (e) {
      // Never reached the assistant, or it refused the message outright.
      setThread((t) => ({ ...t, bubbles: t.bubbles.slice(0, -1) }));
      setDraft(text);
      setSendError(e instanceof ChatError ? e.message : 'Could not reach the assistant.');
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  const remainingLine = !status
    ? loadError
      ? ''
      : 'Checking…'
    : status.status === 'ok'
      ? `${status.remaining} of ${status.limit} messages left today`
      : status.status === 'limit'
        ? `0 of ${status.limit} messages left today`
        : '';

  // The server's sentence for a closed state, unless the conversation already
  // ends with it.
  const last = thread.bubbles[thread.bubbles.length - 1];
  const closedNotice =
    status && closed && status.message && !(last && last.role === 'assistant' && last.text === status.message)
      ? status.message
      : '';

  return (
    <div
      id="site-chat-panel"
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      aria-describedby={noteId}
      tabIndex={-1}
      hidden={!open}
      data-testid="chat-panel"
      className="card anim-enter fixed z-[60] inset-x-2 bottom-2 sm:inset-x-auto sm:right-4 sm:bottom-4 sm:w-[400px] flex flex-col max-h-[calc(100dvh-5.5rem)] sm:max-h-[min(640px,calc(100dvh-6.5rem))] bg-brand-surface focus:outline-none"
      style={open ? undefined : { display: 'none' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-800/80">
        <h2 id={titleId} className="flex items-center gap-2 text-base font-bold min-w-0">
          <Sparkles className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
          <span>
            ProReady<span className="text-gradient">Engineer</span> AI assistant
          </span>
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the assistant"
          className="shrink-0 p-2 -mr-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800/70 transition-colors"
        >
          <X className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      {/* Disclosure: always in view */}
      <p id={noteId} className="px-4 py-2 text-xs leading-snug text-slate-300 bg-slate-950/60 border-b border-slate-800/80">
        {disclosure}
      </p>

      {/* Conversation */}
      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation"
        tabIndex={0}
        className="flex-1 min-h-[9rem] overflow-y-auto px-4 py-4 space-y-3"
      >
        <div className="mr-8 rounded-2xl rounded-tl-sm bg-slate-900 border border-slate-800 px-3.5 py-2.5 text-sm leading-relaxed text-slate-200">
          {GREETING}
        </div>
        {thread.bubbles.map((b, i) =>
          b.role === 'user' ? (
            <div
              key={i}
              className="ml-8 rounded-2xl rounded-tr-sm bg-cyan-500/15 border border-cyan-500/30 px-3.5 py-2.5 text-sm leading-relaxed text-white whitespace-pre-wrap break-words"
            >
              <span className="sr-only">You: </span>
              {b.text}
            </div>
          ) : (
            <div
              key={i}
              data-tone={b.tone ?? 'answer'}
              className={`mr-8 rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words border ${
                b.tone === 'notice'
                  ? 'bg-amber-500/10 border-amber-500/30 text-amber-100'
                  : 'bg-slate-900 border-slate-800 text-slate-200'
              }`}
            >
              <span className="sr-only">Assistant: </span>
              <RichText text={b.text} onNavigate={onClose} />
            </div>
          ),
        )}
        {sending && (
          <div className="mr-8 inline-flex items-center gap-2 rounded-2xl rounded-tl-sm bg-slate-900 border border-slate-800 px-3.5 py-2.5 text-sm text-slate-400">
            <span className="w-3.5 h-3.5 border-2 border-slate-700 border-t-cyan-400 rounded-full animate-spin motion-reduce:animate-none" aria-hidden="true" />
            Thinking…
          </div>
        )}
        {closedNotice && (
          <div
            data-testid="chat-closed-notice"
            className="rounded-xl bg-amber-500/10 border border-amber-500/30 px-3.5 py-2.5 text-sm leading-relaxed text-amber-100"
          >
            <RichText text={closedNotice} onNavigate={onClose} />
          </div>
        )}
        {loadError && !status && (
          <div className="rounded-xl bg-red-950/40 border border-red-900/60 px-3.5 py-2.5 text-sm text-red-200">
            {loadError}{' '}
            <button type="button" onClick={() => void refresh()} className="underline hover:text-white">
              Try again
            </button>
          </div>
        )}
      </div>

      {/* Compose */}
      <form
        className="border-t border-slate-800/80 px-4 pt-3 pb-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        {sendError && (
          <p role="alert" className="mb-2 text-xs text-red-300">
            {sendError}
          </p>
        )}
        <div className="flex items-end gap-2">
          <label className="sr-only" htmlFor="site-chat-input">
            Your message to the AI assistant
          </label>
          <textarea
            id="site-chat-input"
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value.slice(0, maxChars))}
            onKeyDown={onKeyDown}
            rows={2}
            maxLength={maxChars}
            disabled={closed || !status}
            placeholder={closed ? 'The assistant is not taking messages' : 'Type your question'}
            className="flex-1 min-w-0 resize-none rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-cyan-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={closed || !status || sending || !draft.trim()}
            aria-label="Send message"
            className="btn-primary shrink-0 px-3 py-2.5 disabled:opacity-40 disabled:pointer-events-none"
          >
            <Send className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
          <p className="text-xs text-slate-300" data-testid="chat-remaining" aria-live="polite">
            {remainingLine}
            {draft.length > maxChars - 100 && (
              <span className="text-slate-400"> · {maxChars - draft.length} characters left</span>
            )}
          </p>
          {CONSULT_PUBLIC && (
            <Link to={status?.book_url?.startsWith('/') ? status.book_url : '/consult'} onClick={onClose} className="btn-ghost text-xs">
              <CalendarClock className="w-3.5 h-3.5" aria-hidden="true" /> Book a call
              <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
            </Link>
          )}
        </div>
      </form>
    </div>
  );
}
