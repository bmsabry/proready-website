/**
 * Floating admin AI chat — mounted on every admin page by the dashboard shell.
 * Moved verbatim from the old single-file AdminDashboard; behaviour unchanged:
 * tool-calling agent, executed-action chips, and approve/deny gates for
 * emails + mass actions.
 */
import { useState } from 'react';
import {
  AlertTriangle,
  Maximize2,
  Minimize2,
  Send,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { API_BASE, parseHash } from './lib';

type PendingAction = {
  id: string;
  tool: string;
  summary: string;
  expires_at: string;
};

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  // Only set on assistant messages where the agent is asking for confirmation.
  pendingAction?: PendingAction;
  // Only set when the agent silently ran some tools — chips above the bubble.
  actionsExecuted?: string[];
  // True when the agent's pendingAction has been resolved (approved/denied)
  // so we hide the buttons.
  pendingResolved?: boolean;
};


/**
 * Describe the screen Bassam is looking at, for the assistant.
 *
 * Read from the hash rather than passed down as props: the hash is already
 * the single source of truth for admin navigation, so this cannot drift out
 * of sync with what is actually rendered.
 *
 * Why it exists: without it the assistant asked "which course?" while he
 * was standing inside one, with the code on screen above the chat window.
 */
function describeCurrentView(): string {
  if (typeof window === 'undefined') return '';
  const view = parseHash(window.location.hash);
  switch (view.page) {
    case 'courses':
      return view.course
        ? `Admin → Courses → the cohort "${view.course}", on its ${view.tab ?? 'registrations'} tab. ` +
            `"this course" / "these registrants" / "them" means ${view.course}.`
        : 'Admin → Courses (the list of all cohorts).';
    case 'software':
      return view.slug
        ? `Admin → Software → the product "${view.slug}".`
        : 'Admin → Software (all products).';
    case 'support':
      return view.ref
        ? `Admin → Support → ticket #${view.ref}. "this ticket" means #${view.ref}.`
        : 'Admin → Support (the ticket inbox).';
    case 'academy':
      return 'Admin → Academy (recorded on-demand products).';
    case 'comms':
      return 'Admin → Comms (outbound email log and broadcasts).';
    case 'ai':
      return 'Admin → AI Assistant settings.';
    default:
      return 'Admin → Overview.';
  }
}

export default function ChatWidget({ onAuthError }: { onAuthError: () => void }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Apply an AIChatOut response to the conversation.
   * - Adds an assistant message with the reply text
   * - Surfaces actions_executed as a chip list above the bubble
   * - If pending_action is set, the assistant message gets approve/deny buttons
   */
  function applyChatOut(prior: ChatMessage[], data: any): ChatMessage[] {
    const next: ChatMessage = {
      role: 'assistant',
      content: typeof data?.content === 'string' ? data.content : '',
      actionsExecuted:
        Array.isArray(data?.actions_executed) && data.actions_executed.length > 0
          ? data.actions_executed
          : undefined,
      pendingAction:
        data?.pending_action && typeof data.pending_action.id === 'string'
          ? (data.pending_action as PendingAction)
          : undefined,
    };
    return [...prior, next];
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setError(null);
    const userTurn: ChatMessage = { role: 'user', content: text };
    const next = [...messages, userTurn];
    setMessages(next);
    setInput('');
    setBusy(true);
    try {
      // Strip out tool/pending bookkeeping — backend only wants role+content
      // and re-derives the tool history server-side.
      const wirePayload = {
        messages: next.map((m) => ({ role: m.role, content: m.content })),
        // So "email these people" resolves without a round of questions.
        page_context: describeCurrentView(),
      };
      const res = await fetch(`${API_BASE}/api/admin/ai/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(wirePayload),
      });
      if (res.status === 401) {
        onAuthError();
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`;
        setError(detail);
        setMessages(messages); // roll back the optimistic user message
        return;
      }
      setMessages((prev) => applyChatOut(prev, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error.');
      setMessages(messages);
    } finally {
      setBusy(false);
    }
  }

  /** Approve or deny a pending action. The backend resumes the loop and
   * may return another assistant turn (text or another pending_action). */
  async function resolveAction(actionId: string, decision: 'approve' | 'deny') {
    if (busy) return;
    setError(null);
    setBusy(true);
    // Mark the resolved bubble so its buttons disappear.
    setMessages((prev) =>
      prev.map((m) =>
        m.pendingAction?.id === actionId ? { ...m, pendingResolved: true } : m,
      ),
    );
    try {
      const res = await fetch(
        `${API_BASE}/api/admin/ai/actions/${actionId}/${decision}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        },
      );
      if (res.status === 401) {
        onAuthError();
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`);
        return;
      }
      setMessages((prev) => applyChatOut(prev, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error.');
    } finally {
      setBusy(false);
    }
  }

  function clearHistory() {
    setMessages([]);
    setError(null);
  }

  return (
    <>
      {/* Floating launcher button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-4 py-3 rounded-full bg-cyan-500 hover:bg-cyan-400 text-slate-950 shadow-lg shadow-cyan-900/40 transition-colors"
          aria-label="Open admin AI chat"
        >
          <Sparkles className="w-5 h-5" />
          <span className="text-sm font-semibold">Ask the assistant</span>
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div
          className={`fixed bottom-6 right-6 z-40 max-w-[calc(100vw-2rem)] max-h-[calc(100vh-3rem)] bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl shadow-cyan-950/30 flex flex-col overflow-hidden transition-all duration-200 ${
            expanded ? 'w-[820px] h-[80vh]' : 'w-[420px] h-[600px]'
          }`}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-950/60">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-300" />
              <span className="text-sm font-semibold text-white">Assistant</span>
              <span className="text-[10px] text-slate-300 font-mono uppercase tracking-wider">tools on</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setExpanded((v) => !v)}
                title={expanded ? 'Shrink panel' : 'Expand panel'}
                className="p-1.5 text-slate-300 hover:text-white"
              >
                {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
              </button>
              <button
                onClick={clearHistory}
                title="New conversation"
                className="p-1.5 text-slate-300 hover:text-white"
              >
                <Trash2 className="w-4 h-4" />
              </button>
              <button
                onClick={() => setOpen(false)}
                title="Close"
                className="p-1.5 text-slate-300 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 text-sm">
            {messages.length === 0 && (
              <div className="text-slate-300 text-xs leading-relaxed mt-4 space-y-2">
                <p>I can read and edit courses, registrations, and send emails on your behalf. Try:</p>
                <ul className="list-disc list-inside space-y-1 text-slate-300">
                  <li>"how are seats looking on the gas turbine course?"</li>
                  <li>"draft a reminder email to pending registrants"</li>
                  <li>"move day 3 to May 25"</li>
                </ul>
                <p className="text-slate-300">
                  Sending emails and bulk actions (≥3 rows) pause for your Approve in this chat.
                </p>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className="space-y-1">
                {m.actionsExecuted && m.actionsExecuted.length > 0 && (
                  <div className="flex flex-wrap gap-1 mr-auto max-w-[85%]">
                    {m.actionsExecuted.map((a, j) => (
                      <span
                        key={j}
                        className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 font-mono truncate max-w-full"
                        title={a}
                      >
                        {a.length > 80 ? a.slice(0, 80) + '…' : a}
                      </span>
                    ))}
                  </div>
                )}
                <div
                  className={`max-w-[90%] px-3 py-2 rounded-xl whitespace-pre-wrap leading-relaxed break-words overflow-wrap-anywhere ${
                    m.role === 'user'
                      ? 'ml-auto bg-cyan-600/20 border border-cyan-500/40 text-cyan-50'
                      : 'mr-auto bg-slate-800/70 border border-slate-700/60 text-slate-100'
                  }`}
                  style={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
                >
                  {m.content || (m.pendingAction ? '(awaiting approval — see below)' : '')}
                </div>
                {m.pendingAction && !m.pendingResolved && (
                  <div className="mr-auto max-w-[90%] mt-1 p-3 rounded-xl bg-amber-500/10 border border-amber-500/40 space-y-2">
                    <div className="flex items-start gap-2 text-xs text-amber-200">
                      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      <div>
                        <div className="font-semibold mb-0.5">Action requires your approval</div>
                        <div className="text-amber-100/90">{m.pendingAction.summary}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => resolveAction(m.pendingAction!.id, 'deny')}
                        disabled={busy}
                        className="text-xs px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-50"
                      >
                        Deny
                      </button>
                      <button
                        onClick={() => resolveAction(m.pendingAction!.id, 'approve')}
                        disabled={busy}
                        className="text-xs px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
                      >
                        Approve
                      </button>
                    </div>
                  </div>
                )}
                {m.pendingAction && m.pendingResolved && (
                  <div className="mr-auto text-[11px] text-slate-300 italic">
                    decision recorded — see chips above next reply
                  </div>
                )}
              </div>
            ))}
            {busy && (
              <div className="mr-auto px-3 py-2 text-slate-300 text-xs italic">Thinking…</div>
            )}
            {error && (
              <div className="mr-auto max-w-[90%] px-3 py-2 rounded-xl bg-red-950/40 border border-red-900/60 text-red-200 text-xs flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>

          <div className="px-3 py-3 border-t border-slate-800 bg-slate-950/40">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={2}
                placeholder="Ask… (Enter sends, Shift+Enter for newline)"
                className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 resize-none"
              />
              <button
                onClick={send}
                disabled={busy || !input.trim()}
                className="px-3 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="Send"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
