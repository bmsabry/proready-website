/**
 * AI Assistant — endpoint/model/key settings plus the audit activity log.
 * Both moved from the old single-file dashboard; the floating chat widget
 * itself is mounted by the shell on every admin page.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Bot, KeyRound, Lock, MessageSquare, Save, Sparkles } from 'lucide-react';
import { api, reportError, type AuditRow } from './lib';
import { LabeledInput, Notice, RefreshButton, Section } from './ui';

type AISettingsState = {
  api_url: string;
  model_name: string;
  api_key_masked: string;
  is_configured: boolean;
};

export default function AiPage({ onAuthError }: { onAuthError: () => void }) {
  const [state, setState] = useState<AISettingsState | null>(null);
  const [apiUrl, setApiUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [modelName, setModelName] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const body = await api<AISettingsState>('/api/admin/ai/settings');
      setState(body);
      setApiUrl(body.api_url);
      setModelName(body.model_name);
      setApiKey(''); // never re-populate the key field — only show the mask
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setError(null);
    if (!apiUrl.trim() || !modelName.trim() || !apiKey.trim()) {
      setError('All three fields are required to save.');
      return;
    }
    setSaving(true);
    try {
      const body = await api<AISettingsState>('/api/admin/ai/settings', {
        method: 'PUT',
        body: JSON.stringify({
          api_url: apiUrl.trim(),
          api_key: apiKey.trim(),
          model_name: modelName.trim(),
        }),
      });
      setState(body);
      setApiKey('');
      setFlash('Saved. The chat widget will use the new credentials on the next message.');
      window.setTimeout(() => setFlash(null), 5000);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      icon={<Sparkles className="w-5 h-5 text-cyan-300" />}
      title="AI assistant"
      sub="Connect any OpenAI-compatible endpoint — OpenAI, OpenRouter, Together, Groq, Cloudflare AI, or a self-hosted server. The key is encrypted at rest and never sent back to the browser after you save."
    >
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {loading && !state ? (
        <div className="text-slate-300 text-sm">Loading…</div>
      ) : (
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 max-w-2xl space-y-4">
          <LabeledInput
            label="API URL (base or full /chat/completions)"
            value={apiUrl}
            onChange={setApiUrl}
            icon={<KeyRound className="w-3 h-3 text-slate-300" />}
          />
          <LabeledInput
            label="Model name (e.g. gpt-4o-mini, claude-3-5-sonnet, llama-3.3-70b)"
            value={modelName}
            onChange={setModelName}
            icon={<Bot className="w-3 h-3 text-slate-300" />}
          />
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-300 flex items-center gap-1 mb-1">
              <Lock className="w-3 h-3 text-slate-300" />
              API key
              {state?.api_key_masked && (
                <span className="ml-2 text-slate-300 normal-case tracking-normal">
                  current: <span className="font-mono">{state.api_key_masked}</span>
                </span>
              )}
            </span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={state?.is_configured ? 'leave blank to keep, or paste new key' : 'sk-...'}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
            />
            <span className="text-[11px] text-slate-300 mt-1 block">
              Saving requires entering the key again — there's no way to recover the existing one
              from the browser.
            </span>
          </label>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
            <button
              onClick={() => void load()}
              disabled={saving || loading}
              className="btn-secondary text-sm py-2 px-3 disabled:opacity-50"
            >
              Reload
            </button>
            <button
              onClick={() => void save()}
              disabled={saving}
              className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}

      <AIActivitySection onAuthError={onAuthError} />
    </Section>
  );
}

// -----------------------------------------------------------------------------
// AI activity log — viewer for the ai_audit table.
// Shows tool calls, chat turns, and cap-rejected requests in reverse chrono.
// -----------------------------------------------------------------------------

function AIActivitySection({ onAuthError }: { onAuthError: () => void }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await api<AuditRow[]>('/api/admin/ai/audit?limit=100'));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalCost = useMemo(
    () => (rows ? rows.reduce((sum, r) => sum + (r.cost_usd || 0), 0) : 0),
    [rows],
  );

  return (
    <div className="mt-8 max-w-4xl">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-cyan-300" />
          <h3 className="text-sm font-semibold text-white">Activity log</h3>
          <span className="text-xs text-slate-300">
            (last 100 entries — last batch ≈ {totalCost.toFixed(4)} USD)
          </span>
        </div>
        <RefreshButton onClick={() => void load()} loading={loading} small />
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
        {rows === null && loading && <div className="p-6 text-slate-300 text-sm">Loading…</div>}
        {rows && rows.length === 0 && (
          <div className="p-6 text-slate-300 text-sm italic">
            No activity yet. The agent's tool calls, chat turns, and any cap-rejected requests will
            land here.
          </div>
        )}
        {rows && rows.length > 0 && (
          <table className="w-full text-xs">
            <thead className="bg-slate-950/60 text-slate-300 uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2 text-left">When</th>
                <th className="px-3 py-2 text-left">Kind</th>
                <th className="px-3 py-2 text-left">Detail</th>
                <th className="px-3 py-2 text-right">Tokens</th>
                <th className="px-3 py-2 text-right">USD</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((r) => (
                <tr key={r.id} className={r.error ? 'bg-red-950/20' : ''}>
                  <td className="px-3 py-2 text-slate-300 whitespace-nowrap">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-wider border ${
                        r.kind === 'tool'
                          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                          : r.kind === 'cap_hit'
                            ? 'bg-red-500/10 text-red-300 border-red-500/30'
                            : 'bg-slate-700/30 text-slate-300 border-slate-700'
                      }`}
                    >
                      {r.kind === 'tool' ? r.tool_name || 'tool' : r.kind}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-200">
                    <div className="truncate max-w-[420px]" title={r.summary}>
                      {r.summary}
                    </div>
                    {r.error && (
                      <div className="text-red-300 text-[11px] truncate max-w-[420px]" title={r.error}>
                        ↳ {r.error}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-300 whitespace-nowrap">
                    {r.tokens_in || r.tokens_out ? `${r.tokens_in}→${r.tokens_out}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-300 whitespace-nowrap">
                    {r.cost_usd > 0 ? `$${r.cost_usd.toFixed(4)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
