import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Copy,
  GraduationCap,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserPlus,
} from 'lucide-react';

/* Academy administration: on-demand course products, free grants, learners.
 *
 * Separate from CoursesTab, which manages live cohorts (start dates, seats).
 * These are the buy-once recorded courses. */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

type Product = {
  code: string;
  title: string;
  subtitle: string;
  status: 'draft' | 'live';
  price_cents: number;
  currency: string;
  total_hours: number;
  module_count: number;
  lesson_count: number;
  videos_ready: number;
  videos_pending: number;
  active_enrollments: number;
};

type Learner = {
  id: number;
  email: string;
  full_name: string;
  status: string;
  created_at: string;
  last_login_at: string | null;
  is_owner: boolean;
  has_password: boolean;
  lessons_completed: number;
  quiz_attempts: number;
  enrollments: { product_code: string; status: string; source: string; granted_at: string }[];
};

type Owners = {
  owner_emails: string[];
  admin_email: string;
  env_var: string;
  note: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`);
  return data as T;
}

const money = (cents: number, ccy = 'usd') =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: ccy.toUpperCase(),
    maximumFractionDigits: 0,
  }).format(cents / 100);

export default function AcademyTab({ onAuthError }: { onAuthError: () => void }) {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [learners, setLearners] = useState<Learner[] | null>(null);
  const [owners, setOwners] = useState<Owners | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Free-grant form
  const [grantEmail, setGrantEmail] = useState('');
  const [grantName, setGrantName] = useState('');
  const [grantProduct, setGrantProduct] = useState('');
  const [grantNotify, setGrantNotify] = useState(true);

  // Per-product price edits, held until Save so a stray keystroke can't
  // publish a course at the wrong number.
  const [priceEdits, setPriceEdits] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, l, o] = await Promise.all([
        api<{ products: Product[] }>('/api/admin/academy/products'),
        api<{ learners: Learner[] }>('/api/admin/academy/learners'),
        api<Owners>('/api/admin/academy/owners'),
      ]);
      setProducts(p.products);
      setLearners(l.learners);
      setOwners(o);
      if (!grantProduct && p.products.length) setGrantProduct(p.products[0].code);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Could not load academy data.';
      if (msg.includes('Not authenticated')) return onAuthError();
      setError(msg);
    }
  }, [onAuthError, grantProduct]);

  useEffect(() => {
    if (!API_BASE) {
      setError('VITE_API_BASE is not configured for this build.');
      return;
    }
    load();
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
      setError(e instanceof Error ? e.message : 'Save failed.');
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
        `${grantEmail.trim()} now has free access${grantNotify ? ' and has been emailed a sign-in link' : ''}.`
      );
      setGrantEmail('');
      setGrantName('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Grant failed.');
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
        { method: 'POST', body: JSON.stringify({ email }) }
      );
      const mins = Math.round(res.expires_in_seconds / 60);
      try {
        await navigator.clipboard.writeText(res.link);
        note(`Sign-in link for ${email} copied — valid ${mins} min, single use.`);
      } catch {
        window.prompt(`Sign-in link for ${email} (valid ${mins} min):`, res.link);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create a link.');
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
      setError(e instanceof Error ? e.message : 'Revoke failed.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-8">
      {error && (
        <div className="card p-4 border-amber-500/40 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-200">{error}</p>
        </div>
      )}
      {flash && (
        <div className="card p-4 border-cyan-500/40 flex items-start gap-3">
          <Check className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
          <p className="text-sm text-cyan-200">{flash}</p>
        </div>
      )}

      {/* ---------- Products ---------- */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold flex items-center gap-2">
            <GraduationCap className="w-5 h-5 text-cyan-400" />
            On-demand courses
          </h2>
          <button onClick={load} className="btn-ghost text-xs">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>

        {products === null ? (
          <p className="text-slate-400 text-sm">Loading…</p>
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
                        <span
                          className={`text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border ${
                            p.status === 'live'
                              ? 'text-cyan-300 border-cyan-500/40 bg-cyan-500/10'
                              : 'text-slate-400 border-slate-700 bg-slate-800/60'
                          }`}
                        >
                          {p.status}
                        </span>
                      </div>
                      <p className="text-sm text-slate-400">{p.subtitle}</p>
                      <p className="text-xs text-slate-500 mt-2 font-mono">
                        {p.module_count} modules · {p.lesson_count} lessons ·{' '}
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
                            })
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
      </section>

      {/* ---------- Free access ---------- */}
      <section>
        <h2 className="text-lg font-bold flex items-center gap-2 mb-4">
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
            Lifetime access, no payment. Works whether or not they already have an
            account — if they don't, one is created and the link sets it up.
          </p>
        </form>
      </section>

      {/* ---------- Owner access ---------- */}
      <section>
        <h2 className="text-lg font-bold flex items-center gap-2 mb-4">
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
                These addresses skip every paywall, module lock and mastery gate —
                on this course platform and on the five quiz apps alike. Signing in
                with one opens the whole course whether or not it has been bought
                or published, which is what makes it possible to check a broken
                lesson the way a buyer sees it.
              </p>
              <p className="text-xs text-slate-500 mt-3 leading-relaxed">
                Access is keyed to a proven mailbox, never to a typed address:
                these emails sign in by link only, and a purchase is provisioned
                from Stripe's verified email, so typing an owner address at
                checkout grants nothing. Change the list with the{' '}
                <code className="text-slate-400">{owners.env_var}</code> environment
                variable on the API service (comma-separated).
              </p>
            </>
          )}
        </div>
      </section>

      {/* ---------- Learners ---------- */}
      <section>
        <h2 className="text-lg font-bold mb-4">Learners</h2>
        {learners === null ? (
          <p className="text-slate-400 text-sm">Loading…</p>
        ) : learners.length === 0 ? (
          <p className="text-slate-400 text-sm">Nobody enrolled yet.</p>
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
                {learners.map((l) => (
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
                      {l.full_name && (
                        <div className="text-xs text-slate-500">{l.full_name}</div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {l.is_owner ? (
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
                          everything
                        </span>
                      ) : l.enrollments.filter((e) => e.status === 'active').length === 0 ? (
                        <span className="text-slate-500 text-xs">none</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {l.enrollments
                            .filter((e) => e.status === 'active')
                            .map((e) => (
                              <span
                                key={e.product_code}
                                className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300"
                                title={`via ${e.source}`}
                              >
                                {e.product_code}
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
                          onClick={() => signInLink(l.email)}
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
                            <button
                              key={e.product_code}
                              onClick={() => revoke(l.email, e.product_code)}
                              disabled={busy === l.email + e.product_code}
                              className="text-xs text-slate-500 hover:text-amber-300 inline-flex items-center gap-1 disabled:opacity-40"
                              title={`Revoke ${e.product_code}`}
                            >
                              <Trash2 className="w-3.5 h-3.5" /> Revoke
                            </button>
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
