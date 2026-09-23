/**
 * Website Traffic — visits and page views on proreadyengineer.com, read from
 * Cloudflare Web Analytics (bots excluded) by GET /api/admin/traffic; see
 * backend/app/traffic.py. Admin pages are left out unless included.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Compass, Eye, FileText, Globe2, LineChart, Monitor, MousePointerClick } from 'lucide-react';
import { api, formatDate, reportError } from './lib';
import { EmptyState, HBarList, Kpi, Notice, RefreshButton, Section } from './ui';

// ----- Wire types ------------------------------------------------------------

type Point = { t: string; visits: number; page_views: number };
type Row = { visits: number; page_views: number };

type Traffic = {
  configured: boolean;
  days: number;
  include_admin: boolean;
  ranges: number[];
  source: string;
  error: string;
  since?: string;
  until?: string;
  bucket?: 'hour' | 'day';
  totals?: { visits: number; page_views: number; pages_per_visit: number | null };
  previous?: { visits: number; page_views: number } | null;
  sampled?: boolean;
  series?: Point[];
  pages?: (Row & { path: string })[];
  referrers?: { source: string; visits: number }[];
  countries?: (Row & { country: string })[];
  devices?: (Row & { device: string })[];
  browsers?: (Row & { browser: string })[];
  fetched_at?: string;
};

// ----- Helpers ---------------------------------------------------------------

const RANGE_LABEL: Record<number, string> = {
  1: '24 hours',
  7: '7 days',
  30: '30 days',
  90: '90 days',
};

const regionNames: Intl.DisplayNames | null = (() => {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' });
  } catch {
    return null;
  }
})();

function countryName(code: string): string {
  if (/^[A-Z]{2}$/.test(code) && regionNames) {
    try {
      return regionNames.of(code) ?? code;
    } catch {
      return code;
    }
  }
  return code;
}

function change(now: number, before: number | undefined): string | undefined {
  if (before === undefined) return undefined;
  if (before === 0) return now > 0 ? 'new this period (none the period before)' : undefined;
  const pct = Math.round(((now - before) / before) * 100);
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct}% vs the ${before.toLocaleString()} the period before`;
}

function pointLabel(t: string, bucket: 'hour' | 'day'): string {
  const d = new Date(bucket === 'day' ? `${t}T12:00:00Z` : t);
  return bucket === 'day'
    ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })
    : d.toLocaleString(undefined, { weekday: 'short', hour: 'numeric' });
}

const BROWSER_LABEL: Record<string, string> = {
  ChromeMobile: 'Chrome (phone)',
  MobileSafari: 'Safari (iPhone / iPad)',
  Unknown: 'Other',
};

const DEVICE_LABEL: Record<string, string> = {
  desktop: 'Desktop / laptop',
  mobile: 'Phone',
  tablet: 'Tablet',
};

// ----- Chart -----------------------------------------------------------------

/** Page views (pale) behind visits (solid), one column per day or hour. */
function TrafficChart({ points, bucket }: { points: Point[]; bucket: 'hour' | 'day' }) {
  const max = points.reduce((m, p) => Math.max(m, p.page_views, p.visits), 0) || 1;
  const ticks = points.length > 1 ? [0, Math.floor((points.length - 1) / 2), points.length - 1] : [0];
  return (
    <div>
      <div className="flex items-end gap-px h-40">
        {points.map((p) => (
          <div
            key={p.t}
            className="relative flex-1 min-w-0 h-full flex items-end"
            title={`${pointLabel(p.t, bucket)}: ${p.visits.toLocaleString()} visits, ${p.page_views.toLocaleString()} page views`}
          >
            {p.page_views > 0 ? (
              <div
                className="absolute bottom-0 inset-x-0 rounded-t bg-cyan-500/25"
                style={{ height: `${Math.max(3, (p.page_views / max) * 100)}%` }}
              />
            ) : (
              <div className="absolute bottom-0 inset-x-0 bg-slate-800" style={{ height: 2 }} />
            )}
            {p.visits > 0 && (
              <div
                className="absolute bottom-0 inset-x-[18%] rounded-t bg-gradient-to-t from-blue-500 to-cyan-400"
                style={{ height: `${Math.max(3, (p.visits / max) * 100)}%` }}
              />
            )}
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[11px] text-slate-400 mt-2">
        {ticks.map((i) => (
          <span key={i}>{points[i] ? pointLabel(points[i].t, bucket) : ''}</span>
        ))}
      </div>
      <div className="flex items-center gap-4 text-[11px] text-slate-300 mt-3">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-gradient-to-t from-blue-500 to-cyan-400" />
          Visits
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-cyan-500/25" />
          Page views
        </span>
      </div>
    </div>
  );
}

function Card({
  icon,
  title,
  sub,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  sub?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
        <span className="text-cyan-300">{icon}</span>
        {title}
      </h3>
      {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
      <div className="mt-4">{children}</div>
    </div>
  );
}

// ----- Page ------------------------------------------------------------------

export default function TrafficPage({ onAuthError }: { onAuthError: () => void }) {
  const [days, setDays] = useState(30);
  const [includeAdmin, setIncludeAdmin] = useState(false);
  const [data, setData] = useState<Traffic | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (refresh = false) => {
      setLoading(true);
      setError(null);
      try {
        const q = new URLSearchParams({
          days: String(days),
          include_admin: String(includeAdmin),
          ...(refresh ? { refresh: 'true' } : {}),
        });
        setData(await api<Traffic>(`/api/admin/traffic?${q}`));
      } catch (e) {
        reportError(e, onAuthError, setError);
      } finally {
        setLoading(false);
      }
    },
    [days, includeAdmin, onAuthError],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const countries = useMemo(
    () =>
      (data?.countries ?? [])
        .filter((c) => c.visits > 0 || c.page_views > 0)
        .map((c) => ({ label: countryName(c.country), count: c.visits })),
    [data],
  );

  const t = data?.totals;
  const prev = data?.previous ?? undefined;
  const rangeLabel = RANGE_LABEL[days] ?? `${days} days`;

  return (
    <Section
      icon={<LineChart className="w-5 h-5 text-cyan-300" />}
      title="Website Traffic"
      sub={
        <>
          Visits and page views on proreadyengineer.com, from Cloudflare Web Analytics. Bots are
          excluded, and your own admin pages are left out unless you include them.
        </>
      }
      actions={<RefreshButton onClick={() => void load(true)} loading={loading} />}
    >
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="inline-flex rounded-lg border border-slate-800 bg-slate-900/70 p-1">
          {(data?.ranges ?? [1, 7, 30, 90]).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setDays(r)}
              className={`px-3 py-1.5 text-sm rounded-md transition ${
                r === days
                  ? 'bg-gradient-to-r from-cyan-500 to-blue-600 text-white'
                  : 'text-slate-300 hover:text-white'
              }`}
            >
              {RANGE_LABEL[r] ?? `${r} days`}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={includeAdmin}
            onChange={(e) => setIncludeAdmin(e.target.checked)}
            className="accent-cyan-500"
          />
          Include admin pages
        </label>
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {data?.error && <Notice kind="error">{data.error}</Notice>}

      {data && !data.configured && (
        <EmptyState
          icon={<LineChart className="w-5 h-5" />}
          title="Cloudflare isn't connected yet"
          hint="Add a read-only Cloudflare analytics key as CF_ANALYTICS_TOKEN in Render's environment settings, and this page fills in."
        />
      )}

      {!data && loading && <p className="text-sm text-slate-400">Asking Cloudflare…</p>}

      {data?.configured && t && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
            <Kpi
              icon={<MousePointerClick className="w-3.5 h-3.5" />}
              label={`Visits · ${rangeLabel}`}
              value={t.visits.toLocaleString()}
              sub={change(t.visits, prev?.visits) ?? 'Arrivals from outside the site'}
            />
            <Kpi
              icon={<Eye className="w-3.5 h-3.5" />}
              label={`Page views · ${rangeLabel}`}
              value={t.page_views.toLocaleString()}
              sub={change(t.page_views, prev?.page_views) ?? 'Pages loaded in a browser'}
            />
            <Kpi
              icon={<FileText className="w-3.5 h-3.5" />}
              label="Pages per visit"
              value={t.pages_per_visit ?? '—'}
              sub="How far visitors read"
              accent="slate"
            />
            <Kpi
              icon={<Globe2 className="w-3.5 h-3.5" />}
              label="Countries"
              value={countries.length}
              sub={countries[0] ? `Most visits: ${countries[0].label}` : 'No visits yet'}
              accent="emerald"
            />
          </div>

          {data.sampled && (
            <Notice kind="warn">
              Cloudflare counts a small site from a sample (about one page load in ten, scaled back
              up), so these numbers move in steps of about ten. They are the same figures
              Cloudflare's own dashboard shows.
            </Notice>
          )}

          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 mb-4">
            <h3 className="text-sm font-semibold text-white mb-4">
              {data.bucket === 'hour' ? 'By hour' : 'By day'} · {rangeLabel}
            </h3>
            <TrafficChart points={data.series ?? []} bucket={data.bucket ?? 'day'} />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card icon={<FileText className="w-4 h-4" />} title="Most viewed pages">
              {(data.pages ?? []).length === 0 ? (
                <p className="text-sm text-slate-400">No page views in this period.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400">
                      <th className="font-normal pb-2">Page</th>
                      <th className="font-normal pb-2 text-right">Views</th>
                      <th className="font-normal pb-2 text-right">Visits</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.pages ?? []).map((p) => (
                      <tr key={p.path} className="border-t border-slate-800/80">
                        <td className="py-1.5 pr-3 max-w-0 w-full">
                          <a
                            href={`https://proreadyengineer.com${p.path}`}
                            target="_blank"
                            rel="noreferrer"
                            className="block truncate text-slate-200 hover:text-cyan-300"
                            title={p.path}
                          >
                            {p.path}
                          </a>
                        </td>
                        <td className="py-1.5 text-right text-slate-300">
                          {p.page_views.toLocaleString()}
                        </td>
                        <td className="py-1.5 pl-3 text-right text-slate-400">
                          {p.visits.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>

            <Card
              icon={<Compass className="w-4 h-4" />}
              title="Where visitors came from"
              sub="The website a visit arrived from"
            >
              <HBarList
                rows={(data.referrers ?? []).map((r) => ({ label: r.source, count: r.visits }))}
                empty="No visits in this period."
              />
            </Card>

            <Card icon={<Globe2 className="w-4 h-4" />} title="Countries" sub="By visits">
              <HBarList rows={countries} empty="No visits in this period." />
            </Card>

            <Card icon={<Monitor className="w-4 h-4" />} title="Devices and browsers" sub="By visits">
              <HBarList
                rows={(data.devices ?? [])
                  .filter((d) => d.visits > 0)
                  .map((d) => ({ label: DEVICE_LABEL[d.device] ?? d.device, count: d.visits }))}
                empty="No visits in this period."
              />
              <div className="mt-5">
                <HBarList
                  rows={(data.browsers ?? [])
                    .filter((b) => b.visits > 0)
                    .map((b) => ({ label: BROWSER_LABEL[b.browser] ?? b.browser, count: b.visits }))}
                  empty=""
                />
              </div>
            </Card>
          </div>

          <p className="text-[11px] text-slate-500 mt-4">
            {data.source}
            {data.fetched_at ? ` · fetched ${formatDate(data.fetched_at)}` : ''} · refreshed at most
            every 5 minutes. A visit is a page view that arrived from another website, a link or the
            address bar; clicks within the site count as page views only.
          </p>
        </>
      )}
    </Section>
  );
}
