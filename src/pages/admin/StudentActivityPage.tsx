/**
 * Student Activity — one row per trainee: how often they came, what they
 * did each time, the lessons and evaluations they completed, the
 * certificates issued, and anything that looks like account sharing, a
 * leaked copy or other suspicious use.
 *
 * Backed by GET /api/admin/academy/activity (list) and
 * GET /api/admin/academy/activity/{id} (detail); see
 * backend/app/activity_report.py for how every number is worked out.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Award,
  BookOpenCheck,
  Building2,
  CircleHelp,
  EyeOff,
  Satellite,
  Server,
  Smartphone,
  Wifi,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Circle,
  Fingerprint,
  LogIn,
  Search,
  ShieldAlert,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { api, formatDate, fmtDuration, reportError, type AcademyProduct } from './lib';
import { Kpi, Notice, RefreshButton, Section } from './ui';

// ----- Wire types ------------------------------------------------------------

type Severity = '' | 'info' | 'warn' | 'alert';

type Flag = { severity: Severity; title: string; detail: string; at: string | null };

type CourseProgress = {
  code: string;
  title: string;
  lessons_done: number;
  lessons_total: number;
  sets_passed: number;
  sets_total: number;
  complete: boolean;
};

type Cert = {
  tier: string;
  title: string;
  code: string;
  status: string;
  product_code: string;
  course_title: string;
  issued_at: string | null;
  email_sent_at: string | null;
  revoke_reason: string;
};

type Integrity = {
  devices_total: number;
  devices_30d: number;
  devices_seen_once_30d: number;
  ips_30d: number;
  overlaps_30d: number;
  overlaps_different_networks_30d: number;
  overlaps_different_devices_30d: number;
  overlaps_same_browser_30d: number;
  browser_kinds_30d: number;
  copy_alerts: number;
  copy_alerts_open: number;
  launches: number;
  key_refusals: number;
  copies_withdrawn: number;
};

type Row = {
  id: number;
  email: string;
  full_name: string;
  status: string;
  is_owner: boolean;
  created_at: string | null;
  last_seen_at: string | null;
  visits: number;
  visits_tracked: number;
  sign_ins: number;
  courses: CourseProgress[];
  certificates: Cert[];
  integrity: Integrity;
  flags: Flag[];
  worst: Severity;
};

type ListResponse = {
  since: string;
  tracking_since: string | null;
  totals: { students: number; active_7d: number; visits: number; certificates: number; flagged: number };
  learners: Row[];
};

type EventOut = {
  at: string;
  end: string | null;
  kind: string;
  label: string;
  severity: Severity;
  source: 'tracked' | 'records';
  ip: string;
  device: string;
};

type Visit = {
  start: string;
  end: string;
  minutes: number;
  device: string;
  ip: string;
  how: string;
  source: 'tracked' | 'records';
  counts_as_visit: boolean;
  summary: string;
  worst: Severity;
  events: EventOut[];
};

type LessonOut = {
  id: number;
  title: string;
  kind: string;
  done: boolean;
  completed_at: string | null;
  time_s: number;
  last_at: string | null;
};

type EvalOut = {
  item_set: string;
  name: string;
  attempts: number;
  best_score: number | null;
  passed: boolean;
  passed_at: string | null;
  last_at: string | null;
};

type CourseDetail = CourseProgress & {
  modules: { id: number; code: string; title: string; lessons: LessonOut[]; evaluations: EvalOut[] }[];
};

type DeviceOut = {
  browser: string;
  ip: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  seen_count: number;
};

type NetKind =
  | 'mobile' | 'home' | 'business' | 'education' | 'government'
  | 'datacenter' | 'vpn' | 'satellite' | 'local' | 'unknown';

type IpInfo = {
  ip: string;
  place: string;
  city: string;
  country: string;
  country_code: string;
  provider: string;
  netname: string;
  kind: NetKind;
  kind_label: string;
  flags_known: boolean;
};

type Place = {
  place: string;
  country: string;
  provider: string;
  kind: NetKind;
  kind_label: string;
  ips: string[];
  visits: number;
  last_at: string | null;
};

type Detail = {
  since: string;
  tracking_since: string | null;
  learner: Row;
  visits: Visit[];
  courses: CourseDetail[];
  devices: DeviceOut[];
  ip_info: Record<string, IpInfo>;
  locations: Place[];
  ip_lookup_keyed: boolean;
};

// ----- Small pieces ----------------------------------------------------------

const SEV_PILL: Record<Severity, string> = {
  '': 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300',
  info: 'bg-slate-500/10 border-slate-500/30 text-slate-300',
  warn: 'bg-amber-500/10 border-amber-500/40 text-amber-300',
  alert: 'bg-red-500/10 border-red-500/40 text-red-300',
};
const SEV_DOT: Record<Severity, string> = {
  '': 'bg-emerald-400',
  info: 'bg-slate-400',
  warn: 'bg-amber-400',
  alert: 'bg-red-400',
};
const SEV_WORD: Record<Severity, string> = { '': 'None', info: 'Note', warn: 'Concern', alert: 'Alert' };

function Pill({ tone, children, title }: { tone: string; children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded border ${tone}`}
    >
      {children}
    </span>
  );
}

function when(iso: string | null | undefined): string {
  return iso ? formatDate(iso) : '—';
}

function ago(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function time(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  } catch {
    return iso;
  }
}

function duration(minutes: number): string {
  if (minutes < 1) return '< 1 min';
  return fmtDuration(minutes * 60).replace(/ 00s$/, '');
}

function ProgressBar({ c, wide }: { c: CourseProgress; wide?: boolean }) {
  const total = c.lessons_total + c.sets_total;
  const done = c.lessons_done + c.sets_passed;
  const pct = total ? Math.round((100 * done) / total) : 0;
  return (
    <div className="min-w-[150px]" title={`${c.title}: ${c.lessons_done}/${c.lessons_total} lessons, ${c.sets_passed}/${c.sets_total} evaluations`}>
      <div className="flex items-center justify-between gap-2 text-[11px] text-slate-300">
        <span className={wide ? 'text-sm text-white' : 'truncate max-w-[150px]'}>{c.title}</span>
        <span className={c.complete ? 'text-emerald-300' : 'text-slate-400'}>{pct}%</span>
      </div>
      <div className="h-1.5 rounded bg-slate-800 mt-1 overflow-hidden">
        <div
          className={`h-full rounded ${c.complete ? 'bg-emerald-400' : 'bg-gradient-to-r from-cyan-400 to-blue-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-[10px] text-slate-500 mt-0.5">
        {c.lessons_done}/{c.lessons_total} lessons · {c.sets_passed}/{c.sets_total} evaluations
      </div>
    </div>
  );
}

const NET: Record<NetKind, { short: string; tone: string; Icon: typeof Wifi }> = {
  mobile: { short: 'Mobile data', tone: 'text-cyan-300', Icon: Smartphone },
  home: { short: 'Home / office internet', tone: 'text-emerald-300', Icon: Wifi },
  business: { short: 'Company network', tone: 'text-slate-300', Icon: Building2 },
  education: { short: 'University / school', tone: 'text-slate-300', Icon: Building2 },
  government: { short: 'Government network', tone: 'text-slate-300', Icon: Building2 },
  datacenter: { short: 'Data centre', tone: 'text-amber-300', Icon: Server },
  vpn: { short: 'VPN / proxy', tone: 'text-amber-300', Icon: EyeOff },
  satellite: { short: 'Satellite', tone: 'text-slate-300', Icon: Satellite },
  local: { short: 'Private address', tone: 'text-slate-500', Icon: CircleHelp },
  unknown: { short: 'Type not known', tone: 'text-slate-500', Icon: CircleHelp },
};

/** Network kind with its icon: "Mobile data", "Home / office internet"… */
function NetBadge({ kind, title }: { kind: NetKind; title?: string }) {
  const n = NET[kind] ?? NET.unknown;
  return (
    <span className={`inline-flex items-center gap-1 ${n.tone}`} title={title}>
      <n.Icon className="w-3 h-3 shrink-0" aria-hidden="true" />
      {n.short}
    </span>
  );
}

/** An IP with where it is and what kind of network it belongs to. */
function IpCell({ ip, info }: { ip: string; info?: IpInfo }) {
  if (!ip) return <span className="text-slate-500">—</span>;
  return (
    <div className="min-w-[170px]">
      <div className="font-mono text-slate-400">{ip}</div>
      {info?.place && <div className="text-slate-200">{info.place}</div>}
      {info && (
        <div className="text-[11px]">
          <NetBadge kind={info.kind} title={info.kind_label} />
        </div>
      )}
      {info?.provider && (
        <div className="text-[11px] text-slate-500" title={info.netname || undefined}>
          {info.provider}
        </div>
      )}
    </div>
  );
}

// ----- Page ------------------------------------------------------------------

export default function StudentActivityPage({
  onAuthError,
  openId,
  onOpen,
}: {
  onAuthError: () => void;
  openId: number | null;
  onOpen: (id: number | null) => void;
}) {
  const [data, setData] = useState<ListResponse | null>(null);
  const [products, setProducts] = useState<AcademyProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [product, setProduct] = useState('');
  const [days, setDays] = useState(90);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [showOwners, setShowOwners] = useState(false);
  const [tab, setTab] = useState<DetailTab>('visits');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ days: String(days) });
      if (product) qs.set('product_code', product);
      const [list, p] = await Promise.all([
        api<ListResponse>(`/api/admin/academy/activity?${qs}`),
        api<{ products: AcademyProduct[] }>('/api/admin/academy/products'),
      ]);
      setData(list);
      setProducts(p.products);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [days, product, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    return data.learners.filter(
      (r) =>
        (showOwners || !r.is_owner || r.id === openId) &&
        (!flaggedOnly || r.worst === 'warn' || r.worst === 'alert') &&
        (!q || r.email.toLowerCase().includes(q) || r.full_name.toLowerCase().includes(q)),
    );
  }, [data, query, flaggedOnly, showOwners, openId]);

  const toggle = (id: number, t: DetailTab = 'visits') => {
    if (openId === id && t === tab) onOpen(null);
    else {
      setTab(t);
      onOpen(id);
    }
  };

  return (
    <div className="space-y-6">
      <Section
        icon={<Activity className="w-5 h-5 text-cyan-300" />}
        title="Student activity"
        sub="Every visit and what was done in it, lessons and evaluations completed, certificates issued, and integrity or other suspicious activity — per trainee."
        actions={<RefreshButton onClick={() => void load()} loading={loading} />}
      >
        {error && <Notice kind="error">{error}</Notice>}

        {data && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
            <Kpi icon={<Users className="w-3.5 h-3.5" />} label="Students" value={data.totals.students} />
            <Kpi icon={<Activity className="w-3.5 h-3.5" />} label="Active 7 days" value={data.totals.active_7d} accent="emerald" />
            <Kpi icon={<LogIn className="w-3.5 h-3.5" />} label="Visits" value={data.totals.visits} sub={`last ${days === 3650 ? 'all time' : `${days} days`}`} accent="slate" />
            <Kpi icon={<Award className="w-3.5 h-3.5" />} label="Certificates" value={data.totals.certificates} sub="issued" accent="emerald" />
            <Kpi icon={<ShieldAlert className="w-3.5 h-3.5" />} label="Flagged" value={data.totals.flagged} sub="concerns or alerts" accent="amber" />
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search email or name…"
              aria-label="Search students"
              className="bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 w-64 max-w-full"
            />
          </div>
          <select
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            aria-label="Course"
            className="px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-700 text-white text-sm max-w-full"
          >
            <option value="">All courses</option>
            {products.map((p) => (
              <option key={p.code} value={p.code}>
                {p.title}
              </option>
            ))}
          </select>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            aria-label="Period"
            className="px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-700 text-white text-sm"
          >
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last 12 months</option>
            <option value={3650}>All time</option>
          </select>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
            Flagged only
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={showOwners} onChange={(e) => setShowOwners(e.target.checked)} />
            Show owner accounts
          </label>
        </div>

        {data?.tracking_since && (
          <p className="text-xs text-slate-400 mb-3">
            Detailed visit tracking began {when(data.tracking_since)}. Anything earlier is rebuilt from
            the platform's records (sign-in links, lesson completions, evaluations, simulator launches)
            and marked <span className="text-slate-300">from records</span>.
          </p>
        )}

        {!data ? (
          <p className="text-slate-400 text-sm">{loading ? 'Loading…' : '—'}</p>
        ) : rows.length === 0 ? (
          <p className="text-slate-400 text-sm">No students match.</p>
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800">
                  <th className="px-4 py-3">Student</th>
                  <th className="px-4 py-3">Courses</th>
                  <th className="px-4 py-3">Visits</th>
                  <th className="px-4 py-3">Last seen</th>
                  <th className="px-4 py-3">Certificates</th>
                  <th className="px-4 py-3">Integrity</th>
                  <th className="px-4 py-3">Flags</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <StudentRow
                    key={r.id}
                    row={r}
                    open={openId === r.id}
                    tab={tab}
                    setTab={setTab}
                    toggle={toggle}
                    days={days}
                    onAuthError={onAuthError}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

type DetailTab = 'visits' | 'lessons' | 'certificates' | 'integrity' | 'flags';

function StudentRow({
  row: r,
  open,
  tab,
  setTab,
  toggle,
  days,
  onAuthError,
}: {
  row: Row;
  open: boolean;
  tab: DetailTab;
  setTab: (t: DetailTab) => void;
  toggle: (id: number, t?: DetailTab) => void;
  days: number;
  onAuthError: () => void;
}) {
  const issued = r.certificates.filter((c) => c.status === 'issued');
  const concerns = r.flags.filter((f) => f.severity === 'warn' || f.severity === 'alert');
  const i = r.integrity;
  return (
    <>
      <tr
        className={`border-b border-slate-800/60 align-top cursor-pointer hover:bg-slate-800/30 ${open ? 'bg-slate-800/30' : ''}`}
        onClick={() => toggle(r.id, tab)}
      >
        <td className="px-4 py-3 min-w-[230px]">
          <div className="flex items-start gap-2">
            {open ? (
              <ChevronDown className="w-4 h-4 text-cyan-300 mt-0.5 shrink-0" />
            ) : (
              <ChevronRight className="w-4 h-4 text-slate-500 mt-0.5 shrink-0" />
            )}
            <div className="min-w-0">
              <div className="text-white flex flex-wrap items-center gap-2">
                <span className="break-words min-w-0">{r.email}</span>
                {r.is_owner && (
                  <Pill tone="bg-cyan-500/10 border-cyan-500/30 text-cyan-300" title="Owner account">
                    <ShieldCheck className="w-3 h-3" /> Owner
                  </Pill>
                )}
                {r.status !== 'active' && <Pill tone={SEV_PILL.warn}>{r.status}</Pill>}
              </div>
              {r.full_name && <div className="text-xs text-slate-500">{r.full_name}</div>}
            </div>
          </div>
        </td>
        <td className="px-4 py-3">
          {r.courses.length === 0 ? (
            <span className="text-slate-500 text-xs">none</span>
          ) : (
            <div className="space-y-2">
              {r.courses.map((c) => (
                <ProgressBar key={c.code} c={c} />
              ))}
            </div>
          )}
        </td>
        <td className="px-4 py-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggle(r.id, 'visits');
            }}
            className="text-left group"
            title="Show every visit with date, time and what was done"
          >
            <div className="text-white text-lg font-semibold leading-none group-hover:text-cyan-300 underline decoration-dotted decoration-slate-600 underline-offset-4">
              {r.visits}
            </div>
            <div className="text-[11px] text-slate-400 mt-1 whitespace-nowrap">
              {r.sign_ins} sign-in{r.sign_ins === 1 ? '' : 's'}
            </div>
          </button>
        </td>
        <td className="px-4 py-3 text-xs text-slate-300 whitespace-nowrap" title={when(r.last_seen_at)}>
          {ago(r.last_seen_at)}
        </td>
        <td className="px-4 py-3">
          {issued.length === 0 ? (
            <span className="text-slate-500 text-xs">none</span>
          ) : (
            <div className="flex flex-col gap-1">
              {issued.map((c) => (
                <Pill key={c.code} tone="bg-emerald-500/10 border-emerald-500/30 text-emerald-300" title={`${c.title} · ${c.code}`}>
                  <Award className="w-3 h-3" /> {c.tier}
                </Pill>
              ))}
            </div>
          )}
        </td>
        <td className="px-4 py-3 text-xs text-slate-300 whitespace-nowrap">
          <div>
            {i.devices_30d} browser{i.devices_30d === 1 ? '' : 's'} · {i.ips_30d} network{i.ips_30d === 1 ? '' : 's'}
          </div>
          {i.overlaps_30d > 0 && (
            <div className={i.overlaps_different_networks_30d ? 'text-amber-300' : 'text-slate-400'}>
              {i.overlaps_30d}× used at once
            </div>
          )}
          {i.copy_alerts_open > 0 && <div className="text-red-300">{i.copy_alerts_open} copy alert{i.copy_alerts_open === 1 ? '' : 's'}</div>}
        </td>
        <td className="px-4 py-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggle(r.id, 'flags');
            }}
            title={r.flags.map((f) => f.title).join('\n') || 'Nothing flagged'}
          >
            <Pill tone={SEV_PILL[concerns.length ? r.worst : '']}>
              {concerns.length ? (
                <>
                  <AlertTriangle className="w-3 h-3" /> {concerns.length} flag{concerns.length === 1 ? '' : 's'}
                </>
              ) : (
                <>
                  <CircleCheck className="w-3 h-3" /> Clear
                </>
              )}
            </Pill>
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-slate-800/60">
          <td colSpan={7} className="px-3 sm:px-4 py-4 bg-slate-950/60">
            <StudentDetail id={r.id} tab={tab} setTab={setTab} days={days} onAuthError={onAuthError} />
          </td>
        </tr>
      )}
    </>
  );
}

// ----- Detail ----------------------------------------------------------------

function StudentDetail({
  id,
  tab,
  setTab,
  days,
  onAuthError,
}: {
  id: number;
  tab: DetailTab;
  setTab: (t: DetailTab) => void;
  days: number;
  onAuthError: () => void;
}) {
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setD(null);
    setError(null);
    (async () => {
      try {
        const res = await api<Detail>(`/api/admin/academy/activity/${id}?days=${Math.max(days, 365)}`);
        if (!cancelled) setD(res);
      } catch (e) {
        if (!cancelled) reportError(e, onAuthError, setError);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, days, onAuthError]);

  if (error) return <Notice kind="error">{error}</Notice>;
  if (!d) return <p className="text-slate-400 text-sm">Loading…</p>;

  const r = d.learner;
  const concerns = r.flags.filter((f) => f.severity === 'warn' || f.severity === 'alert').length;
  const tabs: { key: DetailTab; label: string; icon: React.ReactNode }[] = [
    { key: 'visits', label: `Visits (${d.visits.filter((v) => v.counts_as_visit).length})`, icon: <LogIn className="w-3.5 h-3.5" /> },
    { key: 'lessons', label: 'Lessons', icon: <BookOpenCheck className="w-3.5 h-3.5" /> },
    { key: 'certificates', label: `Certificates (${r.certificates.length})`, icon: <Award className="w-3.5 h-3.5" /> },
    { key: 'integrity', label: 'Integrity', icon: <Fingerprint className="w-3.5 h-3.5" /> },
    { key: 'flags', label: `Suspicious activity (${concerns})`, icon: <ShieldAlert className="w-3.5 h-3.5" /> },
  ];

  return (
    <div onClick={(e) => e.stopPropagation()}>
      <div className="flex flex-wrap gap-1.5 mb-4" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              tab === t.key
                ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'
                : 'text-slate-300 border-slate-800 hover:bg-slate-800/60'
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'visits' && (
        <>
          {!d.ip_lookup_keyed && <KeyNote />}
          <VisitsTable visits={d.visits} ipInfo={d.ip_info} />
        </>
      )}
      {tab === 'lessons' && <LessonsView courses={d.courses} />}
      {tab === 'certificates' && <CertificatesView certs={r.certificates} />}
      {tab === 'integrity' && (
        <IntegrityView
          i={r.integrity}
          devices={d.devices}
          ipInfo={d.ip_info}
          places={d.locations}
          keyed={d.ip_lookup_keyed}
        />
      )}
      {tab === 'flags' && <FlagsView flags={r.flags} />}
    </div>
  );
}

function KeyNote() {
  return (
    <p className="text-xs text-slate-400 mb-3">
      Locations are shown; home-vs-mobile needs the free ipapi.is key (Render → Environment →{' '}
      <span className="font-mono">IPAPI_KEY</span>).
    </p>
  );
}

function VisitsTable({ visits, ipInfo }: { visits: Visit[]; ipInfo: Record<string, IpInfo> }) {
  const [open, setOpen] = useState<number | null>(null);
  if (visits.length === 0) return <p className="text-slate-400 text-sm">No visits in this period.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[10px] font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800">
            <th className="px-3 py-2">Date &amp; time</th>
            <th className="px-3 py-2">Length</th>
            <th className="px-3 py-2">How</th>
            <th className="px-3 py-2">Device</th>
            <th className="px-3 py-2">IP</th>
            <th className="px-3 py-2">What they did</th>
          </tr>
        </thead>
        <tbody>
          {visits.map((v, idx) => (
            <React.Fragment key={`${v.start}-${idx}`}>
              <tr
                className={`border-b border-slate-800/60 align-top cursor-pointer hover:bg-slate-800/30 ${v.counts_as_visit ? '' : 'opacity-70'}`}
                onClick={() => setOpen(open === idx ? null : idx)}
              >
                <td className="px-3 py-2 whitespace-nowrap text-slate-200">
                  <div className="flex items-center gap-1.5">
                    {open === idx ? <ChevronDown className="w-3.5 h-3.5 text-cyan-300" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-500" />}
                    {v.worst && <span className={`w-2 h-2 rounded-full ${SEV_DOT[v.worst]}`} title={SEV_WORD[v.worst]} />}
                    {when(v.start)}
                  </div>
                  {v.source === 'records' && <div className="text-[10px] text-slate-500 ml-5">from records</div>}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-slate-300">{duration(v.minutes)}</td>
                <td className="px-3 py-2 whitespace-nowrap text-slate-300">{v.how}</td>
                <td className="px-3 py-2 whitespace-nowrap text-slate-300">{v.device || '—'}</td>
                <td className="px-3 py-2 align-top">
                  <IpCell ip={v.ip} info={ipInfo[v.ip]} />
                </td>
                <td className="px-3 py-2 text-slate-200 min-w-[260px]">{v.summary}</td>
              </tr>
              {open === idx && (
                <tr className="border-b border-slate-800/60 bg-slate-900/60">
                  <td colSpan={6} className="px-3 py-3">
                    <ol className="space-y-1.5">
                      {v.events.map((e, j) => (
                        <li key={j} className="flex items-start gap-3">
                          <span className="font-mono text-slate-500 whitespace-nowrap w-20 shrink-0">{time(e.at)}</span>
                          <span className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${SEV_DOT[e.severity === 'info' ? '' : e.severity]}`} />
                          <span className={e.severity === 'alert' ? 'text-red-300' : e.severity === 'warn' ? 'text-amber-300' : 'text-slate-200'}>
                            {e.label}
                            {e.ip && e.ip !== v.ip && (
                              <span className="text-slate-500">
                                {' '}· <span className="font-mono">{e.ip}</span>
                                {ipInfo[e.ip]?.place ? ` (${ipInfo[e.ip].place}, ${NET[ipInfo[e.ip].kind]?.short ?? ''})` : ''}
                              </span>
                            )}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </td>
                </tr>
              )}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LessonsView({ courses }: { courses: CourseDetail[] }) {
  if (courses.length === 0) return <p className="text-slate-400 text-sm">Not enrolled in any course.</p>;
  return (
    <div className="space-y-5">
      {courses.map((c) => (
        <div key={c.code}>
          <div className="max-w-md mb-3">
            <ProgressBar c={c} wide />
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {c.modules.map((m) => (
              <div key={m.id} className="rounded-xl border border-slate-800 p-3">
                <div className="text-sm text-white font-medium mb-2">{m.title}</div>
                <ul className="space-y-1">
                  {m.lessons.map((l) => (
                    <li key={l.id} className="flex items-start gap-2 text-xs">
                      {l.done ? (
                        <CircleCheck className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
                      ) : (
                        <Circle className="w-3.5 h-3.5 text-slate-600 mt-0.5 shrink-0" />
                      )}
                      <span className={`flex-1 ${l.done ? 'text-slate-200' : 'text-slate-400'}`}>{l.title}</span>
                      <span className="text-slate-500 whitespace-nowrap">
                        {l.done ? (l.completed_at ? when(l.completed_at) : 'done') : l.time_s ? `${fmtDuration(l.time_s)} so far` : ''}
                      </span>
                    </li>
                  ))}
                  {m.evaluations.map((ev) => (
                    <li key={ev.item_set} className="flex items-start gap-2 text-xs border-t border-slate-800/60 pt-1 mt-1">
                      {ev.passed ? (
                        <Award className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
                      ) : (
                        <Circle className="w-3.5 h-3.5 text-slate-600 mt-0.5 shrink-0" />
                      )}
                      <span className={`flex-1 ${ev.passed ? 'text-slate-200' : 'text-slate-400'}`}>
                        {ev.name}
                        {ev.attempts > 0 && (
                          <span className="text-slate-500">
                            {' '}
                            · best {Math.round(ev.best_score ?? 0)}% · {ev.attempts} attempt{ev.attempts === 1 ? '' : 's'}
                          </span>
                        )}
                      </span>
                      <span className="text-slate-500 whitespace-nowrap">
                        {ev.passed ? `passed ${when(ev.passed_at)}` : ev.attempts ? 'not passed yet' : 'not taken'}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CertificatesView({ certs }: { certs: Cert[] }) {
  if (certs.length === 0) return <p className="text-slate-400 text-sm">No certificates issued.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[10px] font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800">
            <th className="px-3 py-2">Certificate</th>
            <th className="px-3 py-2">Course</th>
            <th className="px-3 py-2">Code</th>
            <th className="px-3 py-2">Issued</th>
            <th className="px-3 py-2">Emailed</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {certs.map((c) => (
            <tr key={c.code} className="border-b border-slate-800/60 last:border-0">
              <td className="px-3 py-2 text-slate-200">{c.title}</td>
              <td className="px-3 py-2 text-slate-300">{c.course_title || c.product_code}</td>
              <td className="px-3 py-2 font-mono">
                <a href={`/verify/${c.code}`} target="_blank" rel="noreferrer" className="text-cyan-300 hover:underline">
                  {c.code}
                </a>
              </td>
              <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{when(c.issued_at)}</td>
              <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{when(c.email_sent_at)}</td>
              <td className="px-3 py-2">
                <Pill tone={c.status === 'issued' ? SEV_PILL[''] : SEV_PILL.warn} title={c.revoke_reason || undefined}>
                  {c.status}
                </Pill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IntegrityView({
  i,
  devices,
  ipInfo,
  places,
  keyed,
}: {
  i: Integrity;
  devices: DeviceOut[];
  ipInfo: Record<string, IpInfo>;
  places: Place[];
  keyed: boolean;
}) {
  const tiles: [string, number, string?][] = [
    ['Browser sessions, 30 days', i.devices_30d, `${i.browser_kinds_30d} kind${i.browser_kinds_30d === 1 ? '' : 's'} of browser${i.devices_seen_once_30d ? ` · ${i.devices_seen_once_30d} seen once` : ''}`],
    ['Networks, 30 days', i.ips_30d],
    [
      'Used at once, 30 days',
      i.overlaps_30d,
      i.overlaps_30d
        ? `${i.overlaps_different_networks_30d} different networks · ${i.overlaps_different_devices_30d} different devices · ${i.overlaps_same_browser_30d} same browser type`
        : undefined,
    ],
    ['Protected launches', i.launches, i.copies_withdrawn ? `${i.copies_withdrawn} copies withdrawn` : undefined],
    ['Copy alerts', i.copy_alerts, i.copy_alerts ? `${i.copy_alerts_open} not reviewed` : undefined],
    ['Unlock keys refused', i.key_refusals],
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
        {tiles.map(([label, value, sub]) => (
          <div key={label} className="rounded-xl border border-slate-800 p-3">
            <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
            <div className="text-xl text-white font-semibold mt-1">{value}</div>
            {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-400">
        To withdraw a protected copy or end a live simulator session, use the course's Integrity tab.
      </p>
      <div>
        <div className="text-sm text-white font-medium mb-2">Where this account was used</div>
        {!keyed && <KeyNote />}
        {places.length === 0 ? (
          <p className="text-slate-400 text-xs">No addresses recorded in this period.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800">
                  <th className="px-3 py-2">Place</th>
                  <th className="px-3 py-2">Network</th>
                  <th className="px-3 py-2">Provider</th>
                  <th className="px-3 py-2">Visits</th>
                  <th className="px-3 py-2">Last seen</th>
                  <th className="px-3 py-2">IP addresses</th>
                </tr>
              </thead>
              <tbody>
                {places.map((p, k) => (
                  <tr key={k} className="border-b border-slate-800/60 last:border-0 align-top">
                    <td className="px-3 py-2 text-slate-200">{p.place}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <NetBadge kind={p.kind} title={p.kind_label} />
                    </td>
                    <td className="px-3 py-2 text-slate-300">{p.provider || '—'}</td>
                    <td className="px-3 py-2 text-slate-300">{p.visits}</td>
                    <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{when(p.last_at)}</td>
                    <td className="px-3 py-2 font-mono text-slate-400">{p.ips.join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {devices.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[10px] font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800">
                <th className="px-3 py-2">Browser</th>
                <th className="px-3 py-2">Last IP</th>
                <th className="px-3 py-2">First seen</th>
                <th className="px-3 py-2">Last seen</th>
                <th className="px-3 py-2">Times seen</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((dv, k) => (
                <tr key={k} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-3 py-2 text-slate-200 whitespace-nowrap">{dv.browser}</td>
                  <td className="px-3 py-2 align-top">
                    <IpCell ip={dv.ip} info={ipInfo[dv.ip]} />
                  </td>
                  <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{when(dv.first_seen_at)}</td>
                  <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{when(dv.last_seen_at)}</td>
                  <td className="px-3 py-2 text-slate-300">{dv.seen_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FlagsView({ flags }: { flags: Flag[] }) {
  if (flags.length === 0)
    return (
      <p className="text-emerald-300 text-sm flex items-center gap-2">
        <CircleCheck className="w-4 h-4" /> Nothing suspicious in this period.
      </p>
    );
  return (
    <ul className="space-y-2">
      {flags.map((f, k) => (
        <li key={k} className="rounded-xl border border-slate-800 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={SEV_PILL[f.severity]}>{SEV_WORD[f.severity]}</Pill>
            <span className="text-sm text-white">{f.title}</span>
            {f.at && <span className="text-xs text-slate-500">{when(f.at)}</span>}
          </div>
          {f.detail && <p className="text-xs text-slate-400 mt-1.5">{f.detail}</p>}
        </li>
      ))}
    </ul>
  );
}
