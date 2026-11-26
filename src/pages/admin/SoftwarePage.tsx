/**
 * Software — the product registry (all products incl. hidden, with add/edit)
 * and, per product, the download + app-telemetry detail views that used to be
 * hardcoded to pro3dworks. All telemetry sections are parameterized by slug.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Copy,
  Download,
  Globe2,
  KeyRound,
  MonitorDown,
  Pencil,
  Plus,
  Save,
  ShieldBan,
  Sparkles,
  X,
} from 'lucide-react';
import {
  API_BASE,
  api,
  reportError,
  fetchOpts,
  formatDate,
  fmtInt,
  type SoftwareItem,
  countryName,
} from './lib';
import {
  HBarList,
  LabeledInput,
  LabeledSelect,
  Notice,
  RefreshButton,
  Section,
  StatusBadge,
} from './ui';

type Props = {
  slug: string | null;
  openSlug: (slug: string | null) => void;
  onAuthError: () => void;
};

export default function SoftwarePage({ slug, openSlug, onAuthError }: Props) {
  const [items, setItems] = useState<SoftwareItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editSlug, setEditSlug] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api<SoftwareItem[]>('/api/admin/software'));
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

  async function create(input: {
    slug: string;
    name: string;
    blurb: string;
    asset_path: string;
    latest_version: string;
  }): Promise<boolean> {
    setError(null);
    try {
      const created = await api<SoftwareItem>('/api/admin/software', {
        method: 'POST',
        body: JSON.stringify({ ...input, status: 'live' }),
      });
      setItems((prev) => (prev ? [...prev, created] : [created]));
      setShowCreate(false);
      note(`"${created.name}" registered — its download and telemetry slugs are now valid.`);
      return true;
    } catch (e) {
      reportError(e, onAuthError, setError);
      return false;
    }
  }

  async function patch(s: string, body: Record<string, unknown>): Promise<boolean> {
    setError(null);
    try {
      const updated = await api<SoftwareItem>(`/api/admin/software/${encodeURIComponent(s)}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      setItems((prev) => (prev ? prev.map((i) => (i.slug === s ? updated : i)) : prev));
      return true;
    } catch (e) {
      reportError(e, onAuthError, setError);
      return false;
    }
  }

  // ----- Detail view ---------------------------------------------------------
  if (slug) {
    const item = items?.find((i) => i.slug === slug) ?? null;
    return (
      <div>
        <button onClick={() => openSlug(null)} className="btn-ghost text-xs mb-3">
          ← All software
        </button>
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <div className="min-w-0">
            <div className="text-xs font-mono text-slate-400">{slug}</div>
            <h1 className="text-2xl font-bold text-white break-words">{item?.name ?? slug}</h1>
          </div>
          {item && <StatusBadge status={item.status} />}
          {item?.latest_version && (
            <span className="text-sm text-slate-300 font-mono">v{item.latest_version}</span>
          )}
        </div>
        {error && <Notice kind="error">{error}</Notice>}
        <DownloadsSection slug={slug} onAuthError={onAuthError} />
        <AppTelemetrySection slug={slug} />
        <SoftwareLicensesSection onAuthError={onAuthError} productFilter={slug} />
      </div>
    );
  }

  // ----- Registry ------------------------------------------------------------
  return (
    <Section
      icon={<MonitorDown className="w-5 h-5 text-cyan-300" />}
      title="Software"
      sub="Registered products drive the public downloads page and validate telemetry slugs. Hidden products keep their history but leave the site."
      actions={
        <>
          <RefreshButton onClick={() => void load()} loading={loading} />
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="btn-primary flex items-center gap-2 text-sm py-2 px-3"
          >
            <Plus className="w-4 h-4" />
            Add software
          </button>
        </>
      }
    >
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {showCreate && <NewSoftwareForm onCancel={() => setShowCreate(false)} onCreate={create} />}

      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
        {loading && !items && <div className="p-8 text-sm text-slate-300">Loading software…</div>}
        {items && items.length === 0 && (
          <div className="p-8 text-sm text-slate-300">
            Nothing registered yet — add your first product above.
          </div>
        )}
        {items && items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-950/60 text-slate-300 text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-3">Product</th>
                  <th className="text-left px-4 py-3">Version</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-right px-4 py-3">Downloads</th>
                  <th className="text-right px-4 py-3">Launches</th>
                  <th className="text-right px-4 py-3">Pings</th>
                  <th className="text-right px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {items.map((i) => (
                  <React.Fragment key={i.slug}>
                    <tr className="hover:bg-slate-800/30">
                      <td className="px-4 py-3">
                        <button
                          onClick={() => openSlug(i.slug)}
                          className="text-left group"
                          title="Open telemetry detail"
                        >
                          <div className="text-white font-medium group-hover:text-cyan-300">
                            {i.name}
                          </div>
                          <div className="text-xs font-mono text-slate-500">{i.slug}</div>
                        </button>
                      </td>
                      <td className="px-4 py-3 text-slate-300 font-mono text-xs">
                        {i.latest_version || '—'}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={i.status} />
                      </td>
                      <td className="px-4 py-3 text-right text-slate-200">{fmtInt(i.downloads)}</td>
                      <td className="px-4 py-3 text-right text-slate-300">{fmtInt(i.launches)}</td>
                      <td className="px-4 py-3 text-right text-slate-300">{fmtInt(i.usage_pings)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setEditSlug((s) => (s === i.slug ? null : i.slug))}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200"
                          >
                            <Pencil className="w-3 h-3" />
                            Edit
                          </button>
                          <button
                            onClick={() =>
                              void patch(i.slug, {
                                status: i.status === 'live' ? 'hidden' : 'live',
                              })
                            }
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200"
                            title={
                              i.status === 'live'
                                ? 'Hide from the public site (history kept)'
                                : 'Publish on the public site'
                            }
                          >
                            {i.status === 'live' ? 'Hide' : 'Go live'}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {editSlug === i.slug && (
                      <tr>
                        <td colSpan={7} className="px-4 pb-4 bg-slate-950/40">
                          <EditSoftwareForm
                            item={i}
                            onCancel={() => setEditSlug(null)}
                            onSave={async (body) => {
                              const ok = await patch(i.slug, body);
                              if (ok) {
                                setEditSlug(null);
                                note(`Saved ${i.slug}.`);
                              }
                            }}
                          />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <SoftwareLicensesSection onAuthError={onAuthError} />
    </Section>
  );
}

function NewSoftwareForm({
  onCancel,
  onCreate,
}: {
  onCancel: () => void;
  onCreate: (input: {
    slug: string;
    name: string;
    blurb: string;
    asset_path: string;
    latest_version: string;
  }) => Promise<boolean>;
}) {
  const [slug, setSlug] = useState('');
  const [name, setName] = useState('');
  const [blurb, setBlurb] = useState('');
  const [assetPath, setAssetPath] = useState('');
  const [version, setVersion] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const ok = await onCreate({
      slug: slug.trim(),
      name: name.trim(),
      blurb: blurb.trim(),
      asset_path: assetPath.trim(),
      latest_version: version.trim(),
    });
    setBusy(false);
    if (ok) {
      setSlug('');
      setName('');
      setBlurb('');
      setAssetPath('');
      setVersion('');
    }
  }

  return (
    <form onSubmit={submit} className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 mb-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-white">Add software</h3>
        <button
          type="button"
          onClick={onCancel}
          className="text-slate-300 hover:text-white"
          aria-label="Close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <LabeledInput
          label="Slug (lowercase, hyphens — e.g. pro3dworks)"
          value={slug}
          onChange={setSlug}
          mono
        />
        <LabeledInput label="Name" value={name} onChange={setName} />
        <LabeledInput
          label="Asset path (download file, e.g. downloads/Pro3DWorks.zip)"
          value={assetPath}
          onChange={setAssetPath}
          mono
        />
        <LabeledInput label="Latest version (e.g. 1.4.2)" value={version} onChange={setVersion} mono />
      </div>
      <label className="block mt-3">
        <span className="text-[11px] uppercase tracking-wider text-slate-300 block mb-1">Blurb</span>
        <textarea
          value={blurb}
          onChange={(e) => setBlurb(e.target.value)}
          rows={2}
          className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
        />
      </label>
      <div className="mt-4 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-slate-300 hover:text-white px-3 py-1.5"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={busy || !slug.trim() || !name.trim()}
          className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
        >
          <Plus className="w-4 h-4" />
          {busy ? 'Adding…' : 'Add'}
        </button>
      </div>
    </form>
  );
}

function EditSoftwareForm({
  item,
  onCancel,
  onSave,
}: {
  item: SoftwareItem;
  onCancel: () => void;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const [name, setName] = useState(item.name);
  const [blurb, setBlurb] = useState(item.blurb);
  const [assetPath, setAssetPath] = useState(item.asset_path);
  const [version, setVersion] = useState(item.latest_version);
  const [status, setStatus] = useState<'live' | 'hidden'>(item.status);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await onSave({
      name: name.trim(),
      blurb,
      asset_path: assetPath.trim(),
      latest_version: version.trim(),
      status,
    });
    setBusy(false);
  }

  return (
    <form onSubmit={submit} className="border border-slate-800 rounded-xl p-4 mt-1 bg-slate-900/60">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <LabeledInput label="Name" value={name} onChange={setName} />
        <LabeledInput label="Latest version" value={version} onChange={setVersion} mono />
        <LabeledInput label="Asset path" value={assetPath} onChange={setAssetPath} mono />
        <LabeledSelect
          label="Status"
          value={status}
          onChange={(v) => setStatus(v as 'live' | 'hidden')}
        >
          <option value="live">live — public on the site</option>
          <option value="hidden">hidden — kept, but off the site</option>
        </LabeledSelect>
      </div>
      <label className="block mt-3">
        <span className="text-[11px] uppercase tracking-wider text-slate-300 block mb-1">Blurb</span>
        <textarea
          value={blurb}
          onChange={(e) => setBlurb(e.target.value)}
          rows={2}
          className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
        />
      </label>
      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-slate-300 hover:text-white px-3 py-1.5"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={busy || !name.trim()}
          className="btn-primary flex items-center gap-1 text-sm py-1.5 px-3 disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  );
}

/* ---------------- Per-product download statistics ---------------- */

type DownloadStats = {
  product: string;
  total: number;
  last7: number;
  last30: number;
  by_day: { date: string; count: number }[];
  by_country: { country: string; count: number }[];
  by_referrer: { referrer: string; count: number }[];
  recent: {
    ts: string;
    country: string;
    region: string;
    city: string;
    timezone: string;
    referrer: string;
    user_agent: string;
  }[];
};

function DownloadsSection({ slug, onAuthError }: { slug: string; onAuthError: () => void }) {
  const [stats, setStats] = useState<DownloadStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(
        `${API_BASE}/api/admin/downloads?product=${encodeURIComponent(slug)}`,
        fetchOpts,
      );
      if (res.status === 401) {
        onAuthError();
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStats((await res.json()) as DownloadStats);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load download stats.');
    } finally {
      setLoading(false);
    }
  }, [slug, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxDay = stats?.by_day.reduce((m, d) => Math.max(m, d.count), 0) || 1;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Download className="w-5 h-5 text-cyan-400" /> Downloads
        </h2>
        <RefreshButton onClick={() => void load()} loading={loading} />
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 text-red-200 text-sm px-4 py-3 mb-6">
          {error}
        </div>
      )}
      {loading && !stats && <div className="card p-6 text-sm text-slate-300 mb-6">Loading…</div>}

      {stats && (
        <>
          {/* Counters */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
            {[
              { label: 'All time', value: stats.total },
              { label: 'Last 30 days', value: stats.last30 },
              { label: 'Last 7 days', value: stats.last7 },
            ].map((c) => (
              <div key={c.label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
                <p className="text-sm text-slate-400">{c.label}</p>
                <p className="text-3xl font-bold text-white mt-1">{c.value.toLocaleString()}</p>
              </div>
            ))}
          </div>

          {/* Daily bars (last 30 days) */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 mb-8">
            <p className="text-sm font-semibold text-slate-200 mb-4">Daily downloads — last 30 days</p>
            {stats.by_day.length === 0 ? (
              <p className="text-sm text-slate-400">No downloads recorded yet.</p>
            ) : (
              <div className="flex items-end gap-1 h-28">
                {stats.by_day.map((d) => (
                  <div
                    key={d.date}
                    className="flex-1 flex flex-col items-center gap-1"
                    title={`${d.date}: ${d.count}`}
                  >
                    <div
                      className="w-full rounded-t bg-cyan-500/70"
                      style={{ height: `${Math.max(4, (d.count / maxDay) * 100)}%` }}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="grid lg:grid-cols-2 gap-6 mb-8">
            {/* Countries */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
              <p className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                <Globe2 className="w-4 h-4 text-cyan-400" /> By country
              </p>
              {stats.by_country.length === 0 ? (
                <p className="text-sm text-slate-400">Nothing yet.</p>
              ) : (
                <ul className="space-y-2">
                  {stats.by_country.map((c) => (
                    <li key={c.country} className="flex items-center justify-between text-sm">
                      <span className="text-slate-300">{countryName(c.country)}</span>
                      <span className="text-slate-400">{c.count.toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {/* Referrers */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
              <p className="text-sm font-semibold text-slate-200 mb-3">Top referrers</p>
              {stats.by_referrer.length === 0 ? (
                <p className="text-sm text-slate-400">Direct downloads only so far.</p>
              ) : (
                <ul className="space-y-2">
                  {stats.by_referrer.map((r) => (
                    <li key={r.referrer} className="flex items-center justify-between text-sm gap-4">
                      <span className="text-slate-300 min-w-0 break-all">{r.referrer}</span>
                      <span className="text-slate-400 shrink-0">{r.count.toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Recent rows */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 overflow-x-auto">
            <p className="text-sm font-semibold text-slate-200 mb-3">Most recent downloads</p>
            {stats.recent.length === 0 ? (
              <p className="text-sm text-slate-400">No downloads recorded yet — share the link!</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400 border-b border-slate-800">
                    <th className="py-2 pr-4 font-medium">When</th>
                    <th className="py-2 pr-4 font-medium">Where</th>
                    <th className="py-2 pr-4 font-medium">Referrer</th>
                    <th className="py-2 font-medium">Browser</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent.map((r, i) => (
                    <tr key={`${r.ts}-${i}`} className="border-b border-slate-800/60 text-slate-300">
                      <td className="py-2 pr-4 whitespace-nowrap">{formatDate(r.ts)}</td>
                      <td className="py-2 pr-4 whitespace-nowrap">
                        {[r.city, r.region, countryName(r.country)].filter(Boolean).join(', ') || '(unknown)'}
                      </td>
                      <td className="py-2 pr-4 max-w-[240px] break-all">{r.referrer || '—'}</td>
                      <td className="py-2 max-w-[260px] break-all text-slate-400">{r.user_agent}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ---------- App telemetry (launches + opt-in usage pings) ---------- */

type LaunchStats = {
  product: string;
  total: number;
  last7: number;
  by_version: { version: string; count: number }[];
  top_countries: { country: string; count: number }[];
};

type UsageStats = {
  product: string;
  total_sessions: number;
  last7: number;
  total_minutes: number;
  feature_totals: Record<string, number>;
  by_version: { version: string; count: number }[];
  top_countries: { country: string; count: number }[];
};

const FEATURE_LABELS: Record<string, string> = {
  models_loaded: 'Models loaded',
  identify: 'AI identify & color',
  orient: 'AI auto-orient',
  review: 'AI design review',
  bom: 'AI BOM + cost estimate',
  rename: 'AI rename parts',
  chat: 'AI chat',
  photoreal: 'Photoreal renders',
  other: 'Other',
};

function AppTelemetrySection({ slug }: { slug: string }) {
  const [launches, setLaunches] = useState<LaunchStats | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [l, u] = await Promise.all([
        fetch(`${API_BASE}/api/launches/stats?product=${encodeURIComponent(slug)}`, {
          cache: 'no-store',
        }),
        fetch(`${API_BASE}/api/usage/stats?product=${encodeURIComponent(slug)}`, {
          cache: 'no-store',
        }),
      ]);
      setLaunches(l.ok ? ((await l.json()) as LaunchStats) : null);
      setUsage(u.ok ? ((await u.json()) as UsageStats) : null);
      if (!l.ok && !u.ok)
        setError('Telemetry endpoints not reachable yet (backend may still be deploying).');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load app telemetry.');
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  const features = usage
    ? Object.entries(usage.feature_totals).sort((a, b) => b[1] - a[1])
    : [];

  return (
    <div className="mt-10">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-cyan-400" /> App telemetry
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Launches come from the in-app update check (on by default, off switch in the app). Usage
            pings are strictly opt-in feature counts. Both are anonymous — city-level location only,
            no IP addresses stored.
          </p>
        </div>
        <div className="shrink-0">
          <RefreshButton onClick={() => void load()} loading={loading} />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-200 text-sm px-4 py-3 mb-6">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
        {[
          { label: 'Launches — all time', value: launches?.total },
          { label: 'Launches — last 7 days', value: launches?.last7 },
          { label: 'Top version in the field', value: launches?.by_version[0]?.version },
          { label: 'Usage pings (opt-in)', value: usage?.total_sessions },
          { label: 'Pings — last 7 days', value: usage?.last7 },
          {
            label: 'Hours in app (opted-in)',
            value: usage ? Math.round(usage.total_minutes / 60) : undefined,
          },
        ].map((c) => (
          <div key={c.label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-xs text-slate-400">{c.label}</p>
            <p className="text-2xl font-bold text-white mt-1">
              {c.value === undefined || c.value === null
                ? '—'
                : typeof c.value === 'number'
                  ? c.value.toLocaleString()
                  : c.value}
            </p>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <p className="text-sm font-semibold text-slate-200 mb-3">
            What people actually use (opt-in pings)
          </p>
          <HBarList
            rows={features.map(([k, v]) => ({ label: FEATURE_LABELS[k] ?? k, count: v }))}
            empty="No usage pings yet — they only arrive from users who turn the ping on in the app's Privacy & data dialog."
          />
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <p className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
            <Globe2 className="w-4 h-4 text-cyan-400" /> Launches by country &amp; version
          </p>
          {!launches || launches.top_countries.length === 0 ? (
            <p className="text-sm text-slate-400">No launches recorded yet.</p>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <ul className="space-y-2">
                {launches.top_countries.map((c) => (
                  <li key={c.country} className="flex items-center justify-between text-sm">
                    <span className="text-slate-300">{countryName(c.country)}</span>
                    <span className="text-slate-400">{c.count.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
              <ul className="space-y-2">
                {launches.by_version.map((v) => (
                  <li key={v.version} className="flex items-center justify-between text-sm">
                    <span className="text-slate-300">
                      v{String(v.version || '').replace(/^v/i, '')}
                    </span>
                    <span className="text-slate-400">{v.count.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- Commercial Licenses & 15-Day Trials ---------- */

type AdminLicenseRow = {
  id: number;
  product: string;
  license_key: string;
  license_key_masked: string;
  plan: string;
  plan_label: string;
  tier: string;
  status: string;
  email: string;
  full_name: string;
  company: string;
  max_seats: number;
  seats_used: number | null;
  amount_cents: number;
  currency: string;
  current_period_end: string | null;
  updates_until: string | null;
  valid_major_version: number;
  allow_offline_file: boolean;
  created_at: string | null;
};

type AdminTrialRow = {
  id: number;
  product: string;
  email: string;
  full_name: string;
  company: string;
  machine_id: string;
  machine_name: string;
  app_version: string;
  started_at: string | null;
  expires_at: string | null;
};

function SoftwareLicensesSection({
  onAuthError,
  productFilter,
}: {
  onAuthError: () => void;
  productFilter?: string;
}) {
  const [licenses, setLicenses] = useState<AdminLicenseRow[]>([]);
  const [trials, setTrials] = useState<AdminTrialRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [showComp, setShowComp] = useState(false);

  const [compEmail, setCompEmail] = useState('');
  const [compName, setCompName] = useState('');
  const [compCompany, setCompCompany] = useState('');
  const [compPlan, setCompPlan] = useState('pro_yearly');
  const [compNotes, setCompNotes] = useState('');
  const [compEmailUser, setCompEmailUser] = useState(true);
  const [compBusy, setCompBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [licRows, trialRows] = await Promise.all([
        api<AdminLicenseRow[]>('/api/admin/software/licenses'),
        api<AdminTrialRow[]>('/api/admin/software/trials'),
      ]);
      setLicenses(licRows);
      setTrials(trialRows);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const filteredLicenses =
    productFilter && !productFilter.includes('installer')
      ? licenses.filter((l) => l.product === productFilter)
      : licenses;
  const filteredTrials =
    productFilter && !productFilter.includes('installer')
      ? trials.filter((t) => t.product === productFilter)
      : trials;

  const activeCount = filteredLicenses.filter((l) => l.status === 'active').length;
  const perpetualCount = filteredLicenses.filter(
    (l) => l.plan === 'perpetual' && l.status === 'active',
  ).length;
  const nowMs = Date.now();
  const activeTrialCount = filteredTrials.filter(
    (t) => t.expires_at && new Date(t.expires_at).getTime() > nowMs,
  ).length;

  async function issueComp(e: React.FormEvent) {
    e.preventDefault();
    if (!compEmail.trim()) return;
    setCompBusy(true);
    setError('');
    setMsg('');
    try {
      const created = await api<AdminLicenseRow & { offline_token?: string }>(
        '/api/admin/software/licenses/comp',
        {
          method: 'POST',
          body: JSON.stringify({
            product: 'pro3dworks',
            plan: compPlan,
            email: compEmail.trim(),
            full_name: compName.trim(),
            company: compCompany.trim(),
            notes: compNotes.trim(),
            send_email_to_user: compEmailUser,
          }),
        },
      );
      setMsg(`Issued ${created.license_key} for ${created.email} (${created.plan_label}).`);
      setCompEmail('');
      setCompName('');
      setCompCompany('');
      setCompNotes('');
      setShowComp(false);
      await load();
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setCompBusy(false);
    }
  }

  async function downloadOfflineFile(id: number) {
    setError('');
    setMsg('');
    try {
      const res = await api<{ filename: string; token: string; license_key: string }>(
        `/api/admin/software/licenses/${id}/offline-token`,
      );
      const content = `# Pro3DWorks v3 Offline License (${res.license_key})\n${res.token}\n`;
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.filename || 'pro3dworks.p3dwlic';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      try {
        await navigator.clipboard.writeText(res.token);
      } catch {
        /* ignore clipboard restrictions */
      }
      setMsg(`Downloaded ${res.filename} and copied signed P3DW1 token.`);
    } catch (err) {
      reportError(err, onAuthError, setError);
    }
  }

  async function revokeLicense(row: AdminLicenseRow) {
    const reason = window.prompt(
      `Revoke license ${row.license_key} (${row.email})?\nOptional reason:`,
      'Refunded / revoked by admin',
    );
    if (reason === null) return;
    setError('');
    setMsg('');
    try {
      await api(`/api/admin/software/licenses/${row.id}/revoke`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      setMsg(`Revoked ${row.license_key}.`);
      await load();
    } catch (err) {
      reportError(err, onAuthError, setError);
    }
  }

  return (
    <div className="mt-10 pt-8 border-t border-slate-800/80">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <KeyRound className="w-5 h-5 text-cyan-400" /> Licenses &amp; 15-Day Trials
          </h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Active desktop keys issued via Stripe or manually, offline .p3dwlic tokens, and hardware-bound trials.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowComp((v) => !v)}
            className="btn-primary text-sm py-1.5 px-3 flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" /> Issue Comp / Manual Key
          </button>
          <RefreshButton onClick={() => void load()} loading={loading} />
        </div>
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {msg && <Notice kind="success">{msg}</Notice>}

      {/* Summary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'Active Paid / Comp Keys', value: activeCount },
          { label: 'Perpetual v3.x Keys', value: perpetualCount },
          { label: 'Active 15-Day Trials', value: activeTrialCount },
          { label: 'Total Trials Claimed', value: filteredTrials.length },
        ].map((stat) => (
          <div key={stat.label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-xs text-slate-400">{stat.label}</p>
            <p className="text-2xl font-bold text-white mt-1">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Comp key issuer */}
      {showComp && (
        <form
          onSubmit={(e) => void issueComp(e)}
          className="rounded-xl border border-cyan-500/30 bg-slate-900/80 p-5 mb-6"
        >
          <p className="text-sm font-semibold text-white mb-3">
            Issue Complimentary / Manual Desktop License
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <LabeledInput label="Recipient email" value={compEmail} onChange={setCompEmail} />
            <LabeledInput label="Full name" value={compName} onChange={setCompName} />
            <LabeledInput label="Company / Shop" value={compCompany} onChange={setCompCompany} />
            <LabeledSelect label="Plan" value={compPlan} onChange={setCompPlan}>
              <option value="pro_yearly">Pro Yearly ($249 · 3 seats)</option>
              <option value="pro_monthly">Pro Monthly ($29 · 3 seats)</option>
              <option value="shop_yearly">Shop 5-Pack Yearly ($1,390 · 5 seats)</option>
              <option value="shop_monthly">Shop 5-Pack Monthly ($149 · 5 seats)</option>
              <option value="perpetual">Perpetual v3.x ($599 · offline)</option>
            </LabeledSelect>
          </div>
          <div className="grid sm:grid-cols-2 gap-3 mt-3 items-center">
            <LabeledInput label="Internal notes" value={compNotes} onChange={setCompNotes} />
            <label className="flex items-center gap-2 text-sm text-slate-200 mt-4">
              <input
                type="checkbox"
                checked={compEmailUser}
                onChange={(e) => setCompEmailUser(e.target.checked)}
                className="rounded border-slate-700"
              />
              Email the key directly to the recipient
            </label>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowComp(false)}
              className="text-sm text-slate-300 hover:text-white px-3 py-1.5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={compBusy || !compEmail.trim()}
              className="btn-primary text-sm py-1.5 px-4 disabled:opacity-50"
            >
              {compBusy ? 'Issuing…' : 'Create License Key'}
            </button>
          </div>
        </form>
      )}

      {/* Licenses table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 overflow-x-auto mb-6">
        <p className="text-sm font-semibold text-slate-200 mb-3">
          Issued Licenses ({filteredLicenses.length})
        </p>
        {filteredLicenses.length === 0 ? (
          <p className="text-sm text-slate-400">No software licenses issued yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 text-xs uppercase text-slate-400">
              <tr>
                <th className="py-2 pr-4">Key</th>
                <th className="py-2 pr-4">Customer</th>
                <th className="py-2 pr-4">Plan</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Seats</th>
                <th className="py-2 pr-4">Period / Updates</th>
                <th className="py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {filteredLicenses.map((row) => (
                <tr key={row.id}>
                  <td className="py-2.5 pr-4 font-mono text-xs text-cyan-300 whitespace-nowrap">
                    {row.license_key}
                    <button
                      type="button"
                      title="Copy license key"
                      onClick={() => {
                        void navigator.clipboard?.writeText(row.license_key);
                        setMsg(`Copied ${row.license_key}`);
                      }}
                      className="ml-2 text-slate-400 hover:text-white align-middle"
                    >
                      <Copy className="w-3.5 h-3.5 inline" />
                    </button>
                  </td>
                  <td className="py-2.5 pr-4">
                    <div className="text-white">{row.email}</div>
                    {(row.full_name || row.company) && (
                      <div className="text-xs text-slate-400">
                        {[row.full_name, row.company].filter(Boolean).join(' · ')}
                      </div>
                    )}
                  </td>
                  <td className="py-2.5 pr-4 text-xs">{row.plan_label}</td>
                  <td className="py-2.5 pr-4">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-mono ${
                        row.status === 'active'
                          ? 'bg-emerald-500/15 text-emerald-300'
                          : row.status === 'revoked'
                            ? 'bg-red-500/15 text-red-300'
                            : 'bg-amber-500/15 text-amber-300'
                      }`}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-xs">
                    {row.seats_used ?? 0} / {row.max_seats}
                  </td>
                  <td className="py-2.5 pr-4 text-xs text-slate-400 whitespace-nowrap">
                    {row.current_period_end
                      ? row.current_period_end.slice(0, 10)
                      : row.updates_until
                        ? `Updates → ${row.updates_until.slice(0, 10)}`
                        : '—'}
                  </td>
                  <td className="py-2.5 text-right whitespace-nowrap space-x-2">
                    {row.status !== 'revoked' && (
                      <>
                        <button
                          type="button"
                          onClick={() => void downloadOfflineFile(row.id)}
                          className="text-xs px-2.5 py-1 rounded border border-slate-700 hover:border-cyan-500 text-cyan-300"
                        >
                          .p3dwlic
                        </button>
                        <button
                          type="button"
                          onClick={() => void revokeLicense(row)}
                          className="text-xs px-2.5 py-1 rounded border border-red-500/30 hover:border-red-400 text-red-300 inline-flex items-center gap-1"
                        >
                          <ShieldBan className="w-3 h-3" /> Revoke
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Trials table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 overflow-x-auto">
        <p className="text-sm font-semibold text-slate-200 mb-3">
          Recent 15-Day Trials ({filteredTrials.length})
        </p>
        {filteredTrials.length === 0 ? (
          <p className="text-sm text-slate-400">No desktop trials started yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 text-xs uppercase text-slate-400">
              <tr>
                <th className="py-2 pr-4">Email</th>
                <th className="py-2 pr-4">Company / PC</th>
                <th className="py-2 pr-4">Machine ID</th>
                <th className="py-2 pr-4">Started</th>
                <th className="py-2 pr-4">Expires</th>
                <th className="py-2">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {filteredTrials.map((t) => {
                const active = Boolean(t.expires_at && new Date(t.expires_at).getTime() > nowMs);
                return (
                  <tr key={t.id}>
                    <td className="py-2 pr-4 text-white">{t.email}</td>
                    <td className="py-2 pr-4 text-xs text-slate-300">
                      {[t.full_name, t.company, t.machine_name].filter(Boolean).join(' · ') || '—'}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-400">{t.machine_id}</td>
                    <td className="py-2 pr-4 text-xs text-slate-400">
                      {t.started_at ? t.started_at.slice(0, 10) : '—'}
                    </td>
                    <td className="py-2 pr-4 text-xs text-slate-400">
                      {t.expires_at ? t.expires_at.slice(0, 10) : '—'}
                    </td>
                    <td className="py-2">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-mono ${
                          active
                            ? 'bg-cyan-500/15 text-cyan-300'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {active ? 'Active' : 'Ended'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
