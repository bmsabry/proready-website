/**
 * AI Settings — the one AI connection the whole website uses (support
 * triage and reply drafts, and the admin assistant's chat), a "Test the
 * connection" check that makes one tiny real request of each kind, and the
 * assistant's activity log. The floating chat widget itself is mounted by
 * the shell on every admin page.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bot,
  CheckCircle2,
  CircleDashed,
  KeyRound,
  Loader2,
  Lock,
  MessageSquare,
  Save,
  Sparkles,
  Stethoscope,
  XCircle,
} from 'lucide-react';
import { api, formatDate, reportError, type AuditRow, type SupportAiHealth } from './lib';
import { LabeledInput, Notice, RefreshButton, Section } from './ui';

type AISettingsState = {
  api_url: string;
  model_name: string;
  api_key_masked: string;
  is_configured: boolean;
  health?: SupportAiHealth | null;
};

type DiagnoseStep = {
  key: string;
  title: string;
  status: 'pass' | 'fail' | 'skipped';
  detail: string;
  seconds: number | null;
};

type Diagnosis = {
  ok: boolean;
  model: string;
  provider: string;
  verdict: string;
  steps: DiagnoseStep[];
  checked_at: string;
  health: SupportAiHealth;
};

export default function AiPage({ onAuthError }: { onAuthError: () => void }) {
  const [state, setState] = useState<AISettingsState | null>(null);
  const [apiUrl, setApiUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [modelName, setModelName] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<Diagnosis | null>(null);
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

  async function test() {
    setTesting(true);
    setError(null);
    setResult(null);
    try {
      const r = await api<Diagnosis>('/api/admin/ai/diagnose', { method: 'POST' });
      setResult(r);
      setState((s) => (s ? { ...s, health: r.health } : s));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setTesting(false);
    }
  }

  async function save() {
    setError(null);
    if (!apiUrl.trim() || !modelName.trim()) {
      setError('The API URL and the model name are required.');
      return;
    }
    if (!apiKey.trim() && !state?.api_key_masked) {
      setError('Paste the API key — none is saved yet.');
      return;
    }
    setSaving(true);
    try {
      const body = await api<AISettingsState>('/api/admin/ai/settings', {
        method: 'PUT',
        body: JSON.stringify({
          api_url: apiUrl.trim(),
          api_key: apiKey.trim(), // blank keeps the stored key
          model_name: modelName.trim(),
        }),
      });
      setState((s) => ({ ...body, health: s?.health ?? null }));
      setApiKey('');
      setFlash('Saved. Testing the new settings…');
      window.setTimeout(() => setFlash(null), 4000);
      // A save is exactly when you want to know it works.
      await test();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSaving(false);
    }
  }

  const health = result?.health ?? state?.health ?? null;

  return (
    <Section
      icon={<Sparkles className="w-5 h-5 text-cyan-300" />}
      title="AI settings"
      sub="One AI model for the whole website: automatic support replies, reply drafts and the AI Assistant chat all use this connection. Any OpenAI-compatible provider works (OpenRouter, OpenAI, DeepInfra, Groq…). The key is encrypted and never sent back to the browser."
    >
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {loading && !state ? (
        <div className="text-slate-300 text-sm">Loading…</div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-4">
            <h3 className="text-sm font-semibold text-white">Connection</h3>
            <LabeledInput
              label="API URL (base or full /chat/completions)"
              value={apiUrl}
              onChange={setApiUrl}
              placeholder="https://openrouter.ai/api/v1/"
              icon={<KeyRound className="w-3 h-3 text-slate-300" />}
            />
            <LabeledInput
              label="Model name (as the provider writes it)"
              value={modelName}
              onChange={setModelName}
              placeholder="deepseek/deepseek-v4.1-flash"
              icon={<Bot className="w-3 h-3 text-slate-300" />}
            />
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300 flex items-center gap-1 mb-1">
                <Lock className="w-3 h-3 text-slate-300" />
                API key
                {state?.api_key_masked && (
                  <span className="ml-2 text-slate-300 normal-case tracking-normal">
                    saved: <span className="font-mono">{state.api_key_masked}</span>
                  </span>
                )}
              </span>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={state?.api_key_masked ? 'Leave blank to keep the saved key' : 'Paste the key'}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </label>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                onClick={() => void save()}
                disabled={saving || testing}
                className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
              >
                <Save className="w-4 h-4" />
                {saving ? 'Saving…' : 'Save and test'}
              </button>
            </div>
          </div>

          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Stethoscope className="w-4 h-4 text-cyan-300" />
              <h3 className="text-sm font-semibold text-white">Is it working?</h3>
            </div>
            {/* Once a test has run, its result says it all. */}
            {!result && <HealthLine health={health} />}
            <button
              onClick={() => void test()}
              disabled={testing || saving}
              className="w-full inline-flex items-center justify-center gap-2 text-sm px-4 py-2.5 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-100 hover:bg-cyan-500/30 disabled:opacity-50 transition-colors"
            >
              {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Stethoscope className="w-4 h-4" />}
              {testing ? 'Testing — this takes a few seconds…' : 'Test the connection'}
            </button>
            <p className="text-[11px] text-slate-400">
              Sends one tiny real request of each kind the website makes, using the saved settings.
              Costs a fraction of a cent. Emails nobody.
            </p>
            {result && <DiagnosisResult d={result} />}
          </div>
        </div>
      )}

      <AIActivitySection onAuthError={onAuthError} />
    </Section>
  );
}

/** What real traffic says, before anyone presses the button. */
function HealthLine({ health }: { health: SupportAiHealth | null }) {
  if (!health) return null;
  if (health.state === 'ok') {
    return (
      <p className="text-xs text-emerald-300 flex items-start gap-1.5">
        <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>
          Automatic support replies are on.
          {health.last_ok_at ? ` Last successful answer ${formatDate(health.last_ok_at)}.` : ''}
        </span>
      </p>
    );
  }
  if (health.state === 'down' || health.state === 'off') {
    return (
      <p className="text-xs text-red-300 flex items-start gap-1.5">
        <XCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span className="break-words">
          Automatic support replies are off: {health.error}
          {health.since ? ` (since ${formatDate(health.since)})` : ''}.
        </span>
      </p>
    );
  }
  return (
    <p className="text-xs text-slate-400">
      No AI answers recorded yet — press the button to check.
    </p>
  );
}

function DiagnosisResult({ d }: { d: Diagnosis }) {
  return (
    <div className="space-y-3">
      <div
        className={`rounded-lg border px-3 py-2.5 text-sm flex items-start gap-2 ${
          d.ok
            ? 'border-emerald-500/40 bg-emerald-950/30 text-emerald-100'
            : 'border-red-500/40 bg-red-950/30 text-red-100'
        }`}
      >
        {d.ok ? (
          <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-300" />
        ) : (
          <XCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-300" />
        )}
        <span className="break-words">{d.verdict}</span>
      </div>
      <ol className="space-y-2">
        {d.steps.map((s) => (
          <li key={s.key} className="flex items-start gap-2 text-xs">
            {s.status === 'pass' ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            ) : s.status === 'fail' ? (
              <XCircle className="w-4 h-4 shrink-0 text-red-400" />
            ) : (
              <CircleDashed className="w-4 h-4 shrink-0 text-slate-500" />
            )}
            <div className="min-w-0">
              <div
                className={
                  s.status === 'pass'
                    ? 'text-slate-200'
                    : s.status === 'fail'
                      ? 'text-red-200 font-medium'
                      : 'text-slate-500'
                }
              >
                {s.title}
              </div>
              {s.detail && (
                <div
                  className={`break-words ${s.status === 'fail' ? 'text-red-300' : 'text-slate-400'}`}
                >
                  {s.detail}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
      <p className="text-[11px] text-slate-500">Checked {formatDate(d.checked_at)}.</p>
    </div>
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
