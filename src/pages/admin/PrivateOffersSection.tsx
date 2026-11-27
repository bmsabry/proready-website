/**
 * Private offers — sell a course to one person below the list price.
 *
 * The owner picks the buyer's email, the course and the price. The backend
 * mints a single-use link (/learn/offer/<token>) that opens Stripe Checkout at
 * that price with the buyer's email fixed, so the link is useless to anyone
 * else. Payment grants access and sends the normal welcome email; the offer
 * then shows as paid here. A new price for the same person and course
 * replaces the older link.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Copy, Loader2, Mail, Tag, XCircle } from 'lucide-react';
import { api, reportError, money, type AcademyProduct } from './lib';
import { ConfirmButton, Notice, RefreshButton, Section } from './ui';

export type OfferRow = {
  id: number;
  state: 'open' | 'expired' | 'paid' | 'revoked';
  link: string;
  product_code: string;
  product_title: string;
  email: string;
  full_name: string;
  price_cents: number;
  list_price_cents: number;
  currency: string;
  percent_off: number;
  note: string;
  created_by: string;
  created_at: string | null;
  expires_at: string;
  emailed_at: string | null;
  paid_at: string | null;
  revoked_at: string | null;
  order_id: number | null;
};

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '';

const STATE_STYLE: Record<OfferRow['state'], string> = {
  open: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
  paid: 'bg-cyan-500/20 text-cyan-200 border-cyan-500/40',
  expired: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
  revoked: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
};

const inputCls =
  'w-full px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white text-sm';
const labelCls = 'block text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-1';

export default function PrivateOffersSection({
  products,
  onAuthError,
}: {
  products: AcademyProduct[] | null;
  onAuthError: () => void;
}) {
  const [rows, setRows] = useState<OfferRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [productCode, setProductCode] = useState('');
  const [price, setPrice] = useState('');
  const [days, setDays] = useState('14');
  const [note, setNote] = useState('');
  const [sendEmail, setSendEmail] = useState(true);

  const sellable = useMemo(
    () => (products ?? []).filter((p) => p.status === 'live' && p.price_cents > 0),
    [products],
  );
  const product = sellable.find((p) => p.code === productCode) ?? null;

  useEffect(() => {
    if (!productCode && sellable.length) setProductCode(sellable[0].code);
  }, [sellable, productCode]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<{ offers: OfferRow[] }>('/api/admin/academy/offers');
      setRows(r.offers);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const say = (m: string) => {
    setFlash(m);
    window.setTimeout(() => setFlash(null), 10000);
  };

  const priceCents = Math.round(parseFloat(price || '0') * 100);
  const pctOff =
    product && priceCents > 0 && priceCents < product.price_cents
      ? Math.round((1 - priceCents / product.price_cents) * 100)
      : null;

  const copy = async (row: OfferRow) => {
    try {
      await navigator.clipboard.writeText(row.link);
      setCopied(row.id);
      window.setTimeout(() => setCopied(null), 2500);
    } catch {
      window.prompt('Copy this link:', row.link);
    }
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!product) return;
    if (!(priceCents >= 100)) {
      setError('Enter a price of at least $1. To give the course away, use “Give someone free access”.');
      return;
    }
    if (priceCents >= product.price_cents) {
      setError(`The private price must be below the regular price (${money(product.price_cents, product.currency)}).`);
      return;
    }
    setBusy('create');
    setError(null);
    try {
      const row = await api<OfferRow>('/api/admin/academy/offers', {
        method: 'POST',
        body: JSON.stringify({
          email: email.trim(),
          full_name: name.trim(),
          product_code: product.code,
          price_cents: priceCents,
          valid_days: parseInt(days, 10) || 14,
          note: note.trim(),
          send_email: sendEmail,
        }),
      });
      setRows((prev) => [row, ...(prev ?? []).map((r) =>
        r.state === 'open' && r.email === row.email && r.product_code === row.product_code
          ? { ...r, state: 'revoked' as const }
          : r,
      )]);
      try {
        await navigator.clipboard.writeText(row.link);
      } catch {
        /* clipboard can be blocked; the Copy button is on the row */
      }
      say(
        `Offer created: ${money(row.price_cents, row.currency)} for ${row.email}, valid until ${day(row.expires_at)}. ` +
          (sendEmail
            ? row.emailed_at
              ? 'The link was emailed to them and copied to your clipboard.'
              : 'The email did NOT go out — the link is on your clipboard; send it yourself.'
            : 'The link is on your clipboard — send it to them yourself.'),
      );
      setEmail('');
      setName('');
      setPrice('');
      setNote('');
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  };

  const act = async (row: OfferRow, action: 'revoke' | 'resend') => {
    setBusy(action + row.id);
    setError(null);
    try {
      const updated = await api<OfferRow>(`/api/admin/academy/offers/${row.id}/${action}`, {
        method: 'POST',
      });
      setRows((prev) => (prev ?? []).map((r) => (r.id === row.id ? updated : r)));
      say(action === 'revoke' ? `Link for ${row.email} cancelled.` : `Offer emailed again to ${row.email}.`);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  };

  const open = (rows ?? []).filter((r) => r.state === 'open');
  const closed = (rows ?? []).filter((r) => r.state !== 'open');
  const shown = showClosed ? [...open, ...closed] : open;

  return (
    <Section
      icon={<Tag className="w-5 h-5 text-cyan-400" />}
      title="Sell at a private price"
      sub="A discounted price for one person. They get a link that opens secure Stripe checkout at your price, locked to their email. Paying gives them the course and the usual welcome email automatically."
      actions={<RefreshButton onClick={() => void load()} loading={loading} />}
    >
      {error && <Notice kind="error">{error}</Notice>}
      {flash && (
        <Notice kind="success">
          <span className="inline-flex items-start gap-2">
            <Check className="w-4 h-4 mt-0.5 shrink-0" />
            {flash}
          </span>
        </Notice>
      )}

      <form onSubmit={create} className="card p-5 grid sm:grid-cols-2 gap-4 mb-5">
        <div>
          <label className={labelCls}>Buyer's email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="engineer@company.com"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>Name (optional)</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Course</label>
          <select value={productCode} onChange={(e) => setProductCode(e.target.value)} className={inputCls}>
            {sellable.length === 0 && <option value="">No live, priced courses</option>}
            {sellable.map((p) => (
              <option key={p.code} value={p.code}>
                {p.title} — {money(p.price_cents, p.currency)}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Their price (USD)</label>
            <input
              type="number"
              required
              min={1}
              step="0.01"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder={product ? String(Math.round(product.price_cents / 200)) : ''}
              className={`${inputCls} font-mono`}
            />
            <p className="text-[11px] text-slate-500 mt-1 h-4">
              {pctOff !== null && product
                ? `${pctOff}% off ${money(product.price_cents, product.currency)}`
                : product && priceCents >= product.price_cents
                  ? 'Must be below the regular price'
                  : ''}
            </p>
          </div>
          <div>
            <label className={labelCls}>Valid for (days)</label>
            <input
              type="number"
              min={1}
              max={60}
              value={days}
              onChange={(e) => setDays(e.target.value)}
              className={`${inputCls} font-mono`}
            />
          </div>
        </div>
        <div className="sm:col-span-2">
          <label className={labelCls}>Note to the buyer (optional, shown in the email and on the offer page)</label>
          <input
            type="text"
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Alumni price, as we discussed."
            className={inputCls}
          />
        </div>
        <div className="sm:col-span-2 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={sendEmail}
              onChange={(e) => setSendEmail(e.target.checked)}
              className="accent-cyan-400"
            />
            Email the link to them
          </label>
          <button
            type="submit"
            disabled={busy === 'create' || !product}
            className="btn-primary text-sm ml-auto disabled:opacity-50"
          >
            {busy === 'create' ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Create offer link'}
          </button>
        </div>
      </form>

      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-slate-200">
          {open.length} open offer{open.length === 1 ? '' : 's'}
        </h3>
        {closed.length > 0 && (
          <button
            type="button"
            onClick={() => setShowClosed((v) => !v)}
            className="text-xs text-cyan-300 hover:text-cyan-200"
          >
            {showClosed ? 'Hide' : 'Show'} paid, expired and cancelled ({closed.length})
          </button>
        )}
      </div>

      {rows === null ? (
        <p className="text-slate-400 text-sm">{loading ? 'Loading…' : '—'}</p>
      ) : shown.length === 0 ? (
        <p className="text-slate-400 text-sm">No open offers.</p>
      ) : (
        <div className="space-y-2">
          {shown.map((r) => (
            <div key={r.id} className="bg-slate-900/70 border border-slate-800 rounded-xl p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-white font-semibold">
                    {r.full_name ? `${r.full_name} · ` : ''}
                    {r.email}
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    {r.product_title} ·{' '}
                    <span className="text-slate-200 font-mono">{money(r.price_cents, r.currency)}</span>
                    {r.list_price_cents > 0 && (
                      <>
                        {' '}
                        <span className="line-through">{money(r.list_price_cents, r.currency)}</span> ({r.percent_off}% off)
                      </>
                    )}
                    {' · '}
                    {r.state === 'paid'
                      ? `paid ${day(r.paid_at)}`
                      : r.state === 'revoked'
                        ? `cancelled ${day(r.revoked_at)}`
                        : `${r.state === 'expired' ? 'expired' : 'valid until'} ${day(r.expires_at)}`}
                    {r.state === 'open' && (r.emailed_at ? ` · emailed ${day(r.emailed_at)}` : ' · not emailed')}
                  </div>
                  {r.note && <div className="text-xs text-slate-400 italic mt-1">“{r.note}”</div>}
                </div>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${STATE_STYLE[r.state]}`}>
                  {r.state === 'revoked' ? 'cancelled' : r.state}
                </span>
              </div>
              {r.state === 'open' && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void copy(r)}
                    className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-200 hover:border-cyan-500"
                  >
                    {copied === r.id ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                    {copied === r.id ? 'Copied' : 'Copy link'}
                  </button>
                  <button
                    type="button"
                    disabled={busy === 'resend' + r.id}
                    onClick={() => void act(r, 'resend')}
                    className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-200 hover:border-cyan-500 disabled:opacity-50"
                  >
                    {busy === 'resend' + r.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Mail className="w-3.5 h-3.5" />
                    )}
                    Email again
                  </button>
                  <ConfirmButton
                    message={`Cancel the ${money(r.price_cents, r.currency)} offer for ${r.email}? The link will stop working.`}
                    onConfirm={() => void act(r, 'revoke')}
                    disabled={busy === 'revoke' + r.id}
                    className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-red-900/60 text-red-300 hover:border-red-500 disabled:opacity-50"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    Cancel link
                  </ConfirmButton>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
