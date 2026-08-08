/**
 * Software — the product registry (all products incl. hidden, with add/edit)
 * and, per product, the download + app-telemetry detail views that used to be
 * hardcoded to pro3dworks. All telemetry sections are parameterized by slug.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Download,
  Globe2,
  MonitorDown,
  Pencil,
  Plus,
  Save,
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
            <h1 className="text-2xl font-bold text-white truncate">{item?.name ?? slug}</h1>
          </div>
          {item && <StatusBadge status={item.status} />}
          {item?.latest_version && (
            <span className="text-sm text-slate-300 font-mono">v{item.latest_version}</span>
          )}
        </div>
        {error && <Notice kind="error">{error}</Notice>}
        <DownloadsSection slug={slug} onAuthError={onAuthError} />
        <AppTelemetrySection slug={slug} />
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
                      <span className="text-slate-300 truncate">{r.referrer}</span>
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
                      <td className="py-2 pr-4 max-w-[240px] truncate">{r.referrer || '—'}</td>
                      <td className="py-2 max-w-[260px] truncate text-slate-400">{r.user_agent}</td>
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
                    <span className="text-slate-300">v{v.version}</span>
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
