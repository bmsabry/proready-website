/**
 * Academy — global management of the recorded on-demand products.
 * Absorbed from the previously-orphaned AcademyTab: product price/publish
 * editor, free-access grants, owner list, and the learners table (now
 * searchable) with sign-in links and revokes.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Check,
  Copy,
  GraduationCap,
  KeyRound,
  Loader2,
  Search,
  ShieldCheck,
  Trash2,
  UserPlus,
} from 'lucide-react';
import {
  api,
  reportError,
  money,
  type AcademyProduct,
  type Learner,
  type Owners,
} from './lib';
import { ConfirmButton, Notice, RefreshButton, Section, SettlementBadge, StatusBadge } from './ui';

export default function AcademyPage({ onAuthError }: { onAuthError: () => void }) {
  const [products, setProducts] = useState<AcademyProduct[] | null>(null);
  const [learners, setLearners] = useState<Learner[] | null>(null);
  const [owners, setOwners] = useState<Owners | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Free-grant form
  const [grantEmail, setGrantEmail] = useState('');
  const [grantName, setGrantName] = useState('');
  const [grantProduct, setGrantProduct] = useState('');
  const [grantNotify, setGrantNotify] = useState(true);

  // Learner search
  const [query, setQuery] = useState('');

  // Per-product price edits, held until Save so a stray keystroke can't
  // publish a course at the wrong number.
  const [priceEdits, setPriceEdits] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, l, o] = await Promise.all([
        api<{ products: AcademyProduct[] }>('/api/admin/academy/products'),
        api<{ learners: Learner[] }>('/api/admin/academy/learners'),
        api<Owners>('/api/admin/academy/owners'),
      ]);
      setProducts(p.products);
      setLearners(l.learners);
      setOwners(o);
      setGrantProduct((prev) => prev || (p.products[0]?.code ?? ''));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const note = (m: string) => {
    setFlash(m);
    window.setTimeout(() => setFlash(null), 4000);
  };

  const patchProduct = async (code: string, body: Record<string, unknown>) => {
    setBusy(code);
    setError(null);
    try {
      await api(`/api/admin/academy/products/${code}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      await load();
      note('Saved.');
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  };

  const grant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!grantEmail.trim() || !grantProduct) return;
    setBusy('grant');
    setError(null);
    try {
      await api('/api/admin/academy/grant', {
        method: 'POST',
        body: JSON.stringify({
          email: grantEmail.trim(),
          product_code: grantProduct,
          full_name: grantName.trim(),
          send_email_invite: grantNotify,
        }),
      });
      note(
        `${grantEmail.trim()} now has free access${grantNotify ? ' and has been emailed a sign-in link' : ''}.`,
      );
      setGrantEmail('');
      setGrantName('');
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  };

  /* Mints a single-use sign-in link and puts it on the clipboard. Useful when
   * someone's invitation went to spam, and for opening the course as them to
   * see exactly what they see. */
  const signInLink = async (email: string) => {
    setBusy('link' + email);
    setError(null);
    try {
      const res = await api<{ link: string; expires_in_seconds: number }>(
        '/api/admin/academy/login-link',
        { method: 'POST', body: JSON.stringify({ email }) },
      );
      const mins = Math.round(res.expires_in_seconds / 60);
      try {
        await navigator.clipboard.writeText(res.link);
        note(`Sign-in link for ${email} copied — valid ${mins} min, single use.`);
      } catch {
        window.prompt(`Sign-in link for ${email} (valid ${mins} min):`, res.link);
      }
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  };

  const revoke = async (email: string, productCode: string) => {
    setBusy(email + productCode);
    setError(null);
    try {
      await api('/api/admin/academy/revoke', {
        method: 'POST',
        body: JSON.stringify({ email, product_code: productCode }),
      });
      note(`Access revoked for ${email}.`);
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  };

  const filteredLearners = (learners ?? []).filter((l) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return `${l.email} ${l.full_name}`.toLowerCase().includes(q);
  });

  return (
    <div className="space-y-8">
      <Section
        icon={<GraduationCap className="w-5 h-5 text-cyan-400" />}
        title="Academy"
        sub="Recorded on-demand courses — pricing, publishing, learner access."
        actions={<RefreshButton onClick={() => void load()} loading={loading} />}
      >
        {error && <Notice kind="error">{error}</Notice>}
        {flash && (
          <Notice kind="success">
            <span className="inline-flex items-center gap-2">
              <Check className="w-4 h-4" />
              {flash}
            </span>
          </Notice>
        )}

        {/* ---------- Products ---------- */}
        {products === null ? (
          <p className="text-slate-400 text-sm">{loading ? 'Loading…' : '—'}</p>
        ) : products.length === 0 ? (
          <p className="text-slate-400 text-sm">No on-demand courses yet.</p>
        ) : (
          <div className="space-y-4">
            {products.map((p) => {
              const edited = priceEdits[p.code];
              const priceValue = edited ?? String(p.price_cents / 100);
              const canPublish = p.price_cents > 0;
              return (
                <div key={p.code} className="card p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-semibold text-white">{p.title}</h3>
                        <StatusBadge status={p.status} />
                      </div>
                      <p className="text-sm text-slate-400">{p.subtitle}</p>
                      <p className="text-xs text-slate-500 mt-2 font-mono">
                        {p.code} · {p.module_count} modules · {p.lesson_count} lessons ·{' '}
                        {p.total_hours} hrs · {p.active_enrollments} enrolled
                      </p>
                      {p.videos_pending > 0 && (
                        <p className="text-xs text-amber-300/80 mt-1">
                          {p.videos_pending} lesson videos not uploaded yet
                          {p.status === 'live' && ' — buyers will see gaps'}
                        </p>
                      )}
                    </div>

                    <div className="flex items-end gap-3">
                      <div>
                        <label className="block text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-1">
                          Price ({p.currency.toUpperCase()})
                        </label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={priceValue}
                          onChange={(e) =>
                            setPriceEdits((s) => ({ ...s, [p.code]: e.target.value }))
                          }
                          className="w-28 px-2 py-1.5 rounded-lg bg-slate-900/80 border border-slate-700 text-white text-sm"
                        />
                      </div>
                      <button
                        disabled={busy === p.code || edited === undefined}
                        onClick={() =>
                          patchProduct(p.code, {
                            price_cents: Math.round(Number(priceValue) * 100),
                          }).then(() =>
                            setPriceEdits((s) => {
                              const n = { ...s };
                              delete n[p.code];
                              return n;
                            }),
                          )
                        }
                        className="btn-secondary text-sm disabled:opacity-40"
                      >
                        Save price
                      </button>
                      <button
                        disabled={busy === p.code || (p.status === 'draft' && !canPublish)}
                        onClick={() =>
                          patchProduct(p.code, {
                            status: p.status === 'live' ? 'draft' : 'live',
                          })
                        }
                        className={`${
                          p.status === 'live' ? 'btn-secondary' : 'btn-primary'
                        } text-sm disabled:opacity-40`}
                        title={
                          p.status === 'draft' && !canPublish
                            ? 'Set a price before publishing'
                            : undefined
                        }
                      >
                        {busy === p.code ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : p.status === 'live' ? (
                          'Unpublish'
                        ) : (
                          'Publish'
                        )}
                      </button>
                    </div>
                  </div>

                  <p className="text-xs text-slate-500 mt-4">
                    Currently {money(p.price_cents, p.currency)}.{' '}
                    {p.status === 'draft'
                      ? 'Draft courses are hidden from the catalog and cannot be bought.'
                      : 'Live and purchasable.'}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* ---------- Free access ---------- */}
      <section>
        <h2 className="text-lg font-bold flex items-center gap-2 mb-4 text-white">
          <UserPlus className="w-5 h-5 text-cyan-400" />
          Give someone free access
        </h2>
        <form onSubmit={grant} className="card p-5 grid sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-1">
              Email address
            </label>
            <input
              type="email"
              required
              value={grantEmail}
              onChange={(e) => setGrantEmail(e.target.value)}
              placeholder="engineer@company.com"
              className="w-full px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white text-sm"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-1">
              Name (optional)
            </label>
            <input
              type="text"
              value={grantName}
              onChange={(e) => setGrantName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white text-sm"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono uppercase tracking-widest text-slate-500 mb-1">
              Course
            </label>
            <select
              value={grantProduct}
              onChange={(e) => setGrantProduct(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white text-sm"
            >
              {(products ?? []).map((p) => (
                <option key={p.code} value={p.code}>
                  {p.title}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end gap-4">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={grantNotify}
                onChange={(e) => setGrantNotify(e.target.checked)}
                className="accent-cyan-400"
              />
              Email them a sign-in link
            </label>
            <button
              type="submit"
              disabled={busy === 'grant'}
              className="btn-primary text-sm ml-auto disabled:opacity-50"
            >
              {busy === 'grant' ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Grant access'}
            </button>
          </div>
          <p className="sm:col-span-2 text-xs text-slate-500">
            Lifetime access, no payment. Works whether or not they already have an account — if they
            don't, one is created and the link sets it up.
          </p>
        </form>
      </section>

      {/* ---------- Owner access ---------- */}
      <section>
        <h2 className="text-lg font-bold flex items-center gap-2 mb-4 text-white">
          <ShieldCheck className="w-5 h-5 text-cyan-400" />
          Owner access
        </h2>
        <div className="card p-6">
          {owners === null ? (
            <p className="text-slate-400 text-sm">Loading…</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-2 mb-4">
                {owners.owner_emails.map((e) => (
                  <span
                    key={e}
                    className="inline-flex items-center gap-1.5 text-xs font-mono px-2.5 py-1 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-200"
                  >
                    <ShieldCheck className="w-3.5 h-3.5" />
                    {e}
                  </span>
                ))}
              </div>
              <p className="text-sm text-slate-300 leading-relaxed">
                These addresses skip every paywall, module lock and mastery gate — on this course
                platform and on the five quiz apps alike. Signing in with one opens the whole course
                whether or not it has been bought or published, which is what makes it possible to
                check a broken lesson the way a buyer sees it.
              </p>
              <p className="text-xs text-slate-500 mt-3 leading-relaxed">
                Access is keyed to a proven mailbox, never to a typed address: these emails sign in
                by link only, and a purchase is provisioned from Stripe's verified email, so typing
                an owner address at checkout grants nothing. Change the list with the{' '}
                <code className="text-slate-400">{owners.env_var}</code> environment variable on the
                API service (comma-separated).
              </p>
            </>
          )}
        </div>
      </section>

      {/* ---------- Learners ---------- */}
      <section>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <h2 className="text-lg font-bold text-white">
            Learners{learners ? ` (${filteredLearners.length})` : ''}
          </h2>
          <div className="relative ml-auto">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search email or name…"
              className="bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 w-64 max-w-full"
            />
          </div>
        </div>
        {learners === null ? (
          <p className="text-slate-400 text-sm">{loading ? 'Loading…' : '—'}</p>
        ) : learners.length === 0 ? (
          <p className="text-slate-400 text-sm">Nobody enrolled yet.</p>
        ) : filteredLearners.length === 0 ? (
          <p className="text-slate-400 text-sm">No learners match the search.</p>
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800">
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Courses</th>
                  <th className="px-4 py-3">Progress</th>
                  <th className="px-4 py-3">Last seen</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {filteredLearners.map((l) => (
                  <tr key={l.id} className="border-b border-slate-800/60 last:border-0">
                    <td className="px-4 py-3">
                      <div className="text-white flex items-center gap-2">
                        {l.email}
                        {l.is_owner && (
                          <span
                            className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-300"
                            title="Bypasses every paywall and gate"
                          >
                            <ShieldCheck className="w-3 h-3" /> OWNER
                          </span>
                        )}
                      </div>
                      {l.full_name && <div className="text-xs text-slate-500">{l.full_name}</div>}
                    </td>
                    <td className="px-4 py-3">
                      {l.is_owner ? (
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
                          everything
                        </span>
                      ) : l.enrollments.filter(
                          (e) => e.status === 'active' || e.settlement_status === 'failed',
                        ).length === 0 ? (
                        <span className="text-slate-500 text-xs">none</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {l.enrollments
                            .filter(
                              (e) => e.status === 'active' || e.settlement_status === 'failed',
                            )
                            .map((e) => (
                              <span
                                key={e.product_code}
                                className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300"
                                title={`granted ${e.granted_at}`}
                              >
                                {e.product_code}
                                <span className="text-slate-500"> · {e.source}</span>
                                <SettlementBadge
                                  status={e.settlement_status}
                                  deadline={e.settlement_deadline}
                                />
                              </span>
                            ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs font-mono">
                      {l.lessons_completed} lessons · {l.quiz_attempts} attempts
                      {!l.has_password && (
                        <span
                          className="ml-2 inline-flex items-center gap-1 text-slate-600"
                          title="No quiz-app password set yet — they sign in by link"
                        >
                          <KeyRound className="w-3 h-3" /> link only
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {l.last_login_at ? new Date(l.last_login_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-3">
                        <button
                          onClick={() => void signInLink(l.email)}
                          disabled={busy === 'link' + l.email}
                          className="text-xs text-slate-500 hover:text-cyan-300 inline-flex items-center gap-1 disabled:opacity-40"
                          title="Copy a single-use sign-in link for this person"
                        >
                          {busy === 'link' + l.email ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                          Sign-in link
                        </button>
                        {l.enrollments
                          .filter((e) => e.status === 'active')
                          .map((e) => (
                            <ConfirmButton
                              key={e.product_code}
                              message={`Revoke ${l.email}'s access to ${e.product_code}?`}
                              onConfirm={() => void revoke(l.email, e.product_code)}
                              disabled={busy === l.email + e.product_code}
                              className="text-xs text-slate-500 hover:text-amber-300 inline-flex items-center gap-1 disabled:opacity-40"
                              title={`Revoke ${e.product_code}`}
                            >
                              <Trash2 className="w-3.5 h-3.5" /> Revoke
                            </ConfirmButton>
                          ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
