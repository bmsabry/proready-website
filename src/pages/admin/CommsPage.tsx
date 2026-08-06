/**
 * Comms — the global outbound-email log (every broadcast and automated email,
 * filterable by scope) plus a product-buyers broadcast composer.
 * Course-scoped broadcasts live inside each course workspace's Comms tab.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Mail, Search, Send } from 'lucide-react';
import {
  api,
  reportError,
  formatDate,
  plainTextToEmailHtml,
  type AcademyProduct,
  type EmailLogRow,
  type NotifyResult,
} from './lib';
import {
  LabeledSelect,
  MessageEditor,
  Notice,
  RefreshButton,
  Section,
} from './ui';

export default function CommsPage({ onAuthError }: { onAuthError: () => void }) {
  const [rows, setRows] = useState<EmailLogRow[] | null>(null);
  const [products, setProducts] = useState<AcademyProduct[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Log filters
  const [scopeInput, setScopeInput] = useState('');
  const [scopeApplied, setScopeApplied] = useState('');
  const [okFilter, setOkFilter] = useState<'all' | 'ok' | 'fail'>('all');

  // Product broadcast composer
  const [productCode, setProductCode] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [rawHtml, setRawHtml] = useState(false);
  const [sending, setSending] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = scopeApplied ? `?scope_code=${encodeURIComponent(scopeApplied)}&limit=300` : '?limit=300';
      const [logRes, prodRes] = await Promise.all([
        api<{ rows: EmailLogRow[] }>(`/api/admin/comms/log${qs}`),
        api<{ products: AcademyProduct[] }>('/api/admin/academy/products'),
      ]);
      setRows(logRes.rows);
      setProducts(prodRes.products);
      setProductCode((prev) => prev || (prodRes.products[0]?.code ?? ''));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [scopeApplied, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(
    () =>
      (rows ?? []).filter((r) => {
        if (okFilter === 'ok' && !r.ok) return false;
        if (okFilter === 'fail' && r.ok) return false;
        return true;
      }),
    [rows, okFilter],
  );

  const selectedProduct = products?.find((p) => p.code === productCode) ?? null;

  async function send() {
    if (!productCode || !subject.trim() || !body.trim()) {
      setError('Product, subject, and body are required.');
      return;
    }
    const count = selectedProduct?.active_enrollments ?? 0;
    if (
      !window.confirm(
        `Send "${subject.trim()}" to all active buyers of ${productCode} (~${count} recipient${count === 1 ? '' : 's'})?`,
      )
    ) {
      return;
    }
    setSending(true);
    setError(null);
    try {
      const bodyHtml = rawHtml ? body : plainTextToEmailHtml(body);
      const data = await api<NotifyResult>(
        `/api/admin/products/${encodeURIComponent(productCode)}/notify`,
        { method: 'POST', body: JSON.stringify({ subject: subject.trim(), body_html: bodyHtml }) },
      );
      setFlash(
        `Broadcast sent to ${data.recipients} buyer${data.recipients === 1 ? '' : 's'}` +
          (data.failures > 0 ? ` (${data.failures} failed)` : '') +
          '.',
      );
      window.setTimeout(() => setFlash(null), 6000);
      setSubject('');
      setBody('');
      void load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-8">
      <Section
        icon={<Mail className="w-5 h-5 text-cyan-300" />}
        title="Comms"
        sub="Every outbound email, newest first. Course broadcasts are sent from each course's Comms tab; product-buyer broadcasts go out from here."
        actions={<RefreshButton onClick={() => void load()} loading={loading} />}
      >
        {error && <Notice kind="error">{error}</Notice>}
        {flash && <Notice kind="success">{flash}</Notice>}

        {/* Product broadcast composer */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-4 mb-8 max-w-2xl">
          <h3 className="text-white font-semibold text-sm flex items-center gap-2">
            <Send className="w-4 h-4 text-cyan-300" /> Email a product's buyers
          </h3>
          <LabeledSelect
            label="Product"
            value={productCode}
            onChange={setProductCode}
            disabled={products === null}
          >
            {(products ?? []).map((p) => (
              <option key={p.code} value={p.code}>
                {p.title} ({p.code}) — {p.active_enrollments} active
              </option>
            ))}
          </LabeledSelect>
          <MessageEditor
            subject={subject}
            onSubject={setSubject}
            body={body}
            onBody={setBody}
            rawHtml={rawHtml}
            onRawHtml={setRawHtml}
          />
          <div className="flex items-center justify-end">
            <button
              onClick={() => void send()}
              disabled={sending || !productCode || !subject.trim() || !body.trim()}
              className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
            >
              <Send className="w-4 h-4" />
              {sending
                ? 'Sending…'
                : `Send to ${selectedProduct?.active_enrollments ?? 0} buyer${(selectedProduct?.active_enrollments ?? 0) === 1 ? '' : 's'}`}
            </button>
          </div>
        </div>

        {/* Log filters */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setScopeApplied(scopeInput.trim());
            }}
            className="relative flex items-center gap-2"
          >
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                value={scopeInput}
                onChange={(e) => setScopeInput(e.target.value)}
                placeholder="Filter by scope code (course/product)…"
                className="bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 w-72 max-w-full"
              />
            </div>
            <button type="submit" className="btn-secondary text-xs py-2 px-3">
              Apply
            </button>
            {scopeApplied && (
              <button
                type="button"
                onClick={() => {
                  setScopeInput('');
                  setScopeApplied('');
                }}
                className="text-xs text-slate-400 hover:text-white"
              >
                Clear ({scopeApplied})
              </button>
            )}
          </form>
          <div className="ml-auto flex items-center gap-1">
            {(['all', 'ok', 'fail'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setOkFilter(f)}
                className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                  okFilter === f
                    ? 'bg-cyan-500/20 border-cyan-500/60 text-cyan-200'
                    : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-slate-200'
                }`}
              >
                {f === 'all' ? 'All' : f === 'ok' ? 'Delivered' : 'Failed'}
              </button>
            ))}
          </div>
        </div>

        {/* Log table */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
          {loading && !rows && <div className="p-8 text-sm text-slate-300">Loading email log…</div>}
          {rows && rows.length === 0 && (
            <div className="p-8 text-sm text-slate-300">
              {scopeApplied
                ? `No emails logged for scope "${scopeApplied}".`
                : 'No emails logged yet.'}
            </div>
          )}
          {rows && rows.length > 0 && filtered.length === 0 && (
            <div className="p-8 text-sm text-slate-300">No rows match the current filter.</div>
          )}
          {filtered.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-950/60 text-slate-300 uppercase tracking-wider">
                  <tr>
                    <th className="px-3 py-2 text-left">When</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-left">Scope</th>
                    <th className="px-3 py-2 text-left">Audience</th>
                    <th className="px-3 py-2 text-left">Recipient</th>
                    <th className="px-3 py-2 text-left">Subject</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {filtered.map((r) => (
                    <tr key={r.id} className={r.ok ? '' : 'bg-red-950/20'}>
                      <td className="px-3 py-2 text-slate-400 whitespace-nowrap">
                        {formatDate(r.ts)}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`px-2 py-0.5 rounded-full border text-[10px] ${
                            r.ok
                              ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                              : 'bg-red-500/10 text-red-300 border-red-500/30'
                          }`}
                        >
                          {r.ok ? 'ok' : 'failed'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-300 font-mono whitespace-nowrap">
                        {r.scope_code ? (
                          <span title={r.scope_kind}>{r.scope_code}</span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-slate-400 whitespace-nowrap">
                        {r.audience || r.template || '—'}
                      </td>
                      <td className="px-3 py-2 text-slate-300 max-w-[180px] truncate" title={r.recipient}>
                        {r.recipient}
                      </td>
                      <td className="px-3 py-2 text-slate-200 max-w-[320px] truncate" title={r.subject}>
                        {r.subject}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}
