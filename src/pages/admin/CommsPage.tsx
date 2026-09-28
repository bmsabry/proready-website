/**
 * Comms — every email the website has sent, newest first, each one openable
 * to read exactly what the recipient got; plus a product-buyers broadcast
 * composer. Course-scoped broadcasts live inside each course's Comms tab.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Mail, Search, Send, X } from 'lucide-react';
import {
  api,
  reportError,
  plainTextToEmailHtml,
  type AcademyProduct,
  type EmailLogRow,
  type NotifyResult,
} from './lib';
import { LabeledSelect, MessageEditor, Notice, RefreshButton, Section } from './ui';
import { dayLabel, EmailRow, EmailViewer, useEmailViewer } from './EmailViewer';

type Who = 'all' | 'customers' | 'me';
const PAGE = 200;

export default function CommsPage({ onAuthError }: { onAuthError: () => void }) {
  const [rows, setRows] = useState<EmailLogRow[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [products, setProducts] = useState<AcademyProduct[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Log filters
  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');
  const [who, setWho] = useState<Who>('all');
  const [problems, setProblems] = useState(false);

  // Product broadcast composer — opened on demand; the log is the page.
  const [composerOpen, setComposerOpen] = useState(false);
  const [productCode, setProductCode] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [rawHtml, setRawHtml] = useState(false);
  const [sending, setSending] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const params = useCallback(
    (beforeId?: number) => {
      const p = new URLSearchParams({ limit: String(PAGE), who });
      if (query.trim()) p.set('q', query.trim());
      if (problems) p.set('problems', 'true');
      if (beforeId) p.set('before_id', String(beforeId));
      return p.toString();
    },
    [query, who, problems],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [logRes, prodRes] = await Promise.all([
        api<{ rows: EmailLogRow[]; has_more: boolean }>(`/api/admin/comms/log?${params()}`),
        api<{ products: AcademyProduct[] }>('/api/admin/academy/products'),
      ]);
      setRows(logRes.rows);
      setHasMore(logRes.has_more);
      setProducts(prodRes.products);
      setProductCode((prev) => prev || (prodRes.products[0]?.code ?? ''));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [params, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function loadOlder() {
    const last = rows?.[rows.length - 1];
    if (!last) return;
    setLoadingMore(true);
    try {
      const res = await api<{ rows: EmailLogRow[]; has_more: boolean }>(
        `/api/admin/comms/log?${params(last.id)}`,
      );
      setRows((prev) => [...(prev ?? []), ...res.rows]);
      setHasMore(res.has_more);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoadingMore(false);
    }
  }

  const list = rows ?? [];
  const viewer = useEmailViewer(list);

  // Day headings: a log is read by date first.
  const days = useMemo(() => {
    const out: { label: string; rows: EmailLogRow[] }[] = [];
    for (const r of list) {
      const label = dayLabel(r.ts);
      if (out.length && out[out.length - 1].label === label) out[out.length - 1].rows.push(r);
      else out.push({ label, rows: [r] });
    }
    return out;
  }, [list]);

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

  const filtered = query.trim() || who !== 'all' || problems;

  return (
    <div className="space-y-8">
      <Section
        icon={<Mail className="w-5 h-5 text-cyan-300" />}
        title="Comms"
        sub="Every email the website has sent, newest first. Click one to read it exactly as it was received, with who it went to and whether it was delivered."
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setComposerOpen((v) => !v)}
              className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors"
            >
              <Send className="w-3.5 h-3.5" />
              {composerOpen ? 'Hide composer' : "Email a product's buyers"}
            </button>
            <RefreshButton onClick={() => void load()} loading={loading} />
          </div>
        }
      >
        {error && <Notice kind="error">{error}</Notice>}
        {flash && <Notice kind="success">{flash}</Notice>}

        {/* Product broadcast composer */}
        {composerOpen && (
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
        )}

        {/* Search + filters */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(queryInput.trim());
            }}
            className="relative flex-1 min-w-[14rem] max-w-md"
          >
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="Search recipient, subject, course or ticket…"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-8 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            />
            {(queryInput || query) && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => {
                  setQueryInput('');
                  setQuery('');
                }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </form>
          <div className="flex items-center gap-1">
            {(
              [
                ['all', 'All'],
                ['customers', 'To customers'],
                ['me', 'To me'],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setWho(k)}
                className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                  who === k
                    ? 'bg-cyan-500/20 border-cyan-500/60 text-cyan-200'
                    : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-white'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setProblems((v) => !v)}
            title="Not sent, bounced, suppressed or marked as spam"
            className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
              problems
                ? 'bg-red-500/20 border-red-500/60 text-red-200'
                : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-white'
            }`}
          >
            Problems only
          </button>
        </div>

        {/* The log */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
          {loading && !rows && <div className="p-8 text-sm text-slate-300">Loading emails…</div>}
          {rows && rows.length === 0 && (
            <div className="p-8 text-sm text-slate-300">
              {filtered ? 'No emails match.' : 'No emails sent yet.'}
            </div>
          )}
          {days.map((day) => (
            <div key={day.label}>
              <div className="px-4 py-1.5 text-[11px] uppercase tracking-wider text-slate-400 bg-slate-950/90 border-y border-slate-800 first:border-t-0">
                {day.label}
                <span className="ml-2 normal-case tracking-normal text-slate-600">
                  {day.rows.length} email{day.rows.length === 1 ? '' : 's'}
                </span>
              </div>
              <div className="divide-y divide-slate-800/70">
                {day.rows.map((r) => (
                  <EmailRow
                    key={r.id}
                    r={r}
                    selected={viewer.openId === r.id}
                    onOpen={() => viewer.open(r.id)}
                  />
                ))}
              </div>
            </div>
          ))}
          {hasMore && (
            <div className="p-3 border-t border-slate-800 text-center">
              <button
                onClick={() => void loadOlder()}
                disabled={loadingMore}
                className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                {loadingMore ? 'Loading…' : 'Show older emails'}
              </button>
            </div>
          )}
        </div>
      </Section>

      <EmailViewer
        emailId={viewer.openId}
        onClose={viewer.close}
        onNewer={viewer.newer}
        onOlder={viewer.older}
        onAuthError={onAuthError}
      />
    </div>
  );
}
