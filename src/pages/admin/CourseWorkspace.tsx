/**
 * CourseWorkspace — everything about one cohort in one place, behind internal
 * sub-navigation: Registrations, Buyers (recorded counterpart), Comms,
 * Stats, Materials, Settings.
 *
 * The workspace loads the course record, its stats row, and the academy
 * product list once; tabs that need more (registrations, learners, content,
 * email log) fetch their own.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Ban,
  BarChart3,
  Briefcase,
  Calendar,
  CheckCircle2,
  Clock,
  Copy,
  Eye,
  FileDown,
  FileText,
  GraduationCap,
  HelpCircle,
  Loader2,
  Lock,
  Mail,
  MapPin,
  PlayCircle,
  Plus,
  Save,
  Search,
  Send,
  Settings,
  Trash2,
  Unlock,
  Users,
  X,
  XCircle,
} from 'lucide-react';
import {
  api,
  reportError,
  downloadCsv,
  formatDate,
  formatDay,
  fmtDuration,
  money,
  plainTextToEmailHtml,
  type AcademyProduct,
  type ContentLesson,
  type Course,
  type CoursePatch,
  type CourseStats,
  type CourseTab,
  type EmailLogRow,
  type Learner,
  type NotifyAudience,
  type NotifyResult,
  type ProductContent,
  type Registration,
} from './lib';
import {
  BarChart,
  ConfirmButton,
  EmptyState,
  HBarList,
  Kpi,
  LabeledInput,
  LabeledSelect,
  MessageEditor,
  Notice,
  ProviderBadge,
  RefreshButton,
  SeatsBar,
  StatusBadge,
} from './ui';

type Props = {
  code: string;
  tab: CourseTab;
  onTab: (t: CourseTab) => void;
  onBack: () => void;
  onAuthError: () => void;
};

const TAB_DEFS: { key: CourseTab; label: string; icon: React.ReactNode }[] = [
  { key: 'registrations', label: 'Registrations', icon: <Users className="w-4 h-4" /> },
  { key: 'buyers', label: 'Buyers', icon: <GraduationCap className="w-4 h-4" /> },
  { key: 'comms', label: 'Comms', icon: <Mail className="w-4 h-4" /> },
  { key: 'stats', label: 'Stats', icon: <BarChart3 className="w-4 h-4" /> },
  { key: 'materials', label: 'Materials', icon: <PlayCircle className="w-4 h-4" /> },
  { key: 'settings', label: 'Settings', icon: <Settings className="w-4 h-4" /> },
];

export default function CourseWorkspace({ code, tab, onTab, onBack, onAuthError }: Props) {
  const [course, setCourse] = useState<Course | null>(null);
  const [stats, setStats] = useState<CourseStats | null>(null);
  const [products, setProducts] = useState<AcademyProduct[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, s, p] = await Promise.all([
        api<Course>(`/api/admin/courses/${encodeURIComponent(code)}`),
        api<{ courses: CourseStats[] }>('/api/admin/stats/courses'),
        api<{ products: AcademyProduct[] }>('/api/admin/academy/products'),
      ]);
      setCourse(c);
      setStats(s.courses.find((x) => x.code === code) ?? null);
      setProducts(p.products);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [code, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Merge seat-count changes coming back from mark-paid/cancel responses. */
  const onSeatsChanged = useCallback(() => {
    void load();
  }, [load]);

  return (
    <div>
      {/* Header */}
      <button onClick={onBack} className="btn-ghost text-xs mb-3">
        <ArrowLeft className="w-3.5 h-3.5" /> All courses
      </button>
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="min-w-0">
          <div className="text-xs font-mono text-slate-400">{code}</div>
          <h1 className="text-2xl font-bold text-white truncate">{course?.title ?? '…'}</h1>
        </div>
        {course && <StatusBadge status={course.status} />}
        {course && (
          <span className="text-sm text-slate-300">Starts {formatDay(course.start_date)}</span>
        )}
        <div className="ml-auto">
          <RefreshButton onClick={() => void load()} loading={loading} />
        </div>
      </div>

      {/* Sub-navigation */}
      <div className="flex items-center gap-1 mb-6 border-b border-slate-800 overflow-x-auto">
        {TAB_DEFS.map((t) => (
          <button
            key={t.key}
            onClick={() => onTab(t.key)}
            className={`flex items-center gap-2 text-sm px-3 sm:px-4 py-2 border-b-2 -mb-px whitespace-nowrap transition-colors ${
              tab === t.key
                ? 'border-cyan-400 text-cyan-300'
                : 'border-transparent text-slate-300 hover:text-slate-200'
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      {!course && loading && (
        <div className="card p-8 text-sm text-slate-300">Loading course…</div>
      )}
      {!course && !loading && !error && (
        <div className="card p-8 text-sm text-slate-300">Course not found.</div>
      )}

      {course && tab === 'registrations' && (
        <RegistrationsTab
          code={code}
          course={course}
          onSeatsChanged={onSeatsChanged}
          onAuthError={onAuthError}
        />
      )}
      {course && tab === 'buyers' && (
        <BuyersTab
          course={course}
          stats={stats}
          onAuthError={onAuthError}
          gotoSettings={() => onTab('settings')}
        />
      )}
      {course && tab === 'comms' && (
        <CommsTab code={code} course={course} stats={stats} onAuthError={onAuthError} />
      )}
      {course && tab === 'stats' && <StatsTab course={course} stats={stats} />}
      {course && tab === 'materials' && (
        <MaterialsTab
          course={course}
          onAuthError={onAuthError}
          gotoSettings={() => onTab('settings')}
        />
      )}
      {course && tab === 'settings' && (
        <SettingsTab
          key={course.code}
          course={course}
          products={products}
          onSaved={(c) => {
            setCourse(c);
          }}
          onAuthError={onAuthError}
        />
      )}
    </div>
  );
}

// =============================================================================
// Registrations
// =============================================================================

function RegistrationsTab({
  code,
  course,
  onSeatsChanged,
  onAuthError,
}: {
  code: string;
  course: Course;
  onSeatsChanged: () => void;
  onAuthError: () => void;
}) {
  const [regs, setRegs] = useState<Registration[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'paid' | 'cancelled'>('all');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRegs(await api<Registration[]>(`/api/admin/registrations?course=${encodeURIComponent(code)}`));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [code, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    const c = { pending: 0, paid: 0, cancelled: 0, total: 0 };
    for (const r of regs ?? []) {
      c.total += 1;
      if (r.status === 'pending') c.pending += 1;
      else if (r.status === 'paid') c.paid += 1;
      else if (r.status === 'cancelled') c.cancelled += 1;
    }
    return c;
  }, [regs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (regs ?? []).filter((r) => {
      if (statusFilter !== 'all' && r.status !== statusFilter) return false;
      if (!q) return true;
      return [r.full_name, r.email, r.company, r.job_title, r.location]
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [regs, query, statusFilter]);

  async function action(path: 'mark-paid' | 'cancel', id: number) {
    setBusyId(id);
    setError(null);
    try {
      const body = await api<{ ok: boolean; taken: number; registration: Registration }>(
        `/api/admin/${path}`,
        { method: 'POST', body: JSON.stringify({ registration_id: id }) },
      );
      setRegs((prev) =>
        prev ? prev.map((r) => (r.id === body.registration.id ? body.registration : r)) : prev,
      );
      onSeatsChanged();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusyId(null);
    }
  }

  function exportCsv() {
    downloadCsv(
      `registrations-${code}.csv`,
      [
        'ID',
        'Name',
        'Email',
        'Job title',
        'Company',
        'Years experience',
        'Location',
        'Status',
        'Payment',
        'Registered',
        'Paid at',
      ],
      filtered.map((r) => [
        r.id,
        r.full_name,
        r.email,
        r.job_title,
        r.company,
        r.years_experience,
        r.location,
        r.status,
        r.payment_provider || 'invoice',
        r.created_at,
        r.paid_at ?? '',
      ]),
    );
  }

  return (
    <div>
      {/* KPI row for this course */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Kpi
          icon={<Users className="w-4 h-4" />}
          label="Seats"
          value={`${course.seats_taken} / ${course.total_seats}`}
          sub={`${course.seats_remaining} remaining`}
          accent="cyan"
        />
        <Kpi icon={<Clock className="w-4 h-4" />} label="Pending" value={counts.pending} accent="amber" />
        <Kpi icon={<CheckCircle2 className="w-4 h-4" />} label="Paid" value={counts.paid} accent="emerald" />
        <Kpi icon={<Ban className="w-4 h-4" />} label="Cancelled" value={counts.cancelled} accent="slate" />
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name, email, company…"
            className="bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 w-64 max-w-full"
          />
        </div>
        {(['all', 'pending', 'paid', 'cancelled'] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
              statusFilter === s
                ? 'bg-cyan-500/20 border-cyan-500/60 text-cyan-200'
                : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-slate-200'
            }`}
          >
            {s === 'all' ? `All (${counts.total})` : `${s} (${counts[s]})`}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={exportCsv}
            disabled={filtered.length === 0}
            className="btn-secondary flex items-center gap-2 text-xs py-1.5 px-2.5 disabled:opacity-50"
            title="Download the filtered rows as CSV"
          >
            <FileDown className="w-3.5 h-3.5" />
            CSV ({filtered.length})
          </button>
          <RefreshButton onClick={() => void load()} loading={loading} small />
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
        {loading && !regs && <div className="p-8 text-slate-300 text-sm">Loading registrations…</div>}
        {regs && regs.length === 0 && (
          <div className="p-8 text-slate-300 text-sm">No registrations yet for this course.</div>
        )}
        {regs && regs.length > 0 && filtered.length === 0 && (
          <div className="p-8 text-slate-300 text-sm">No registrations match the current filters.</div>
        )}
        {filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-950/60 text-slate-300 text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-3">Applicant</th>
                  <th className="text-left px-4 py-3">Company / Role</th>
                  <th className="text-left px-4 py-3">Location</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-left px-4 py-3">Payment</th>
                  <th className="text-left px-4 py-3 whitespace-nowrap">Registered</th>
                  <th className="text-right px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {filtered.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-800/30">
                    <td className="px-4 py-3 align-top">
                      <div className="text-white font-medium">{r.full_name}</div>
                      <a
                        href={`mailto:${r.email}`}
                        className="text-xs text-cyan-300 hover:underline flex items-center gap-1 mt-0.5"
                      >
                        <Mail className="w-3 h-3" />
                        {r.email}
                      </a>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="text-slate-200">{r.company}</div>
                      <div className="text-xs text-slate-300 flex items-center gap-1 mt-0.5">
                        <Briefcase className="w-3 h-3" />
                        {r.job_title}
                        <span className="text-slate-500">·</span>
                        {r.years_experience} yrs
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top text-slate-300 whitespace-nowrap">
                      <div className="flex items-center gap-1">
                        <MapPin className="w-3 h-3 text-slate-300" />
                        {r.location}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <StatusBadge status={r.status} />
                      {r.paid_at && (
                        <div className="text-[11px] text-slate-300 mt-1">
                          paid {formatDate(r.paid_at)}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <ProviderBadge provider={r.payment_provider} />
                    </td>
                    <td className="px-4 py-3 align-top text-slate-300 text-xs whitespace-nowrap">
                      {formatDate(r.created_at)}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="flex items-center justify-end gap-2">
                        {r.status !== 'paid' && (
                          <ConfirmButton
                            message={`Mark ${r.full_name} (${r.email}) as paid?`}
                            onConfirm={() => void action('mark-paid', r.id)}
                            disabled={busyId === r.id}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-emerald-600/90 hover:bg-emerald-500 text-white disabled:opacity-50"
                          >
                            <CheckCircle2 className="w-3 h-3" />
                            Mark paid
                          </ConfirmButton>
                        )}
                        {r.status !== 'cancelled' && (
                          <ConfirmButton
                            message={`Cancel ${r.full_name}'s registration? The seat will be released.`}
                            onConfirm={() => void action('cancel', r.id)}
                            disabled={busyId === r.id}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 disabled:opacity-50"
                          >
                            <XCircle className="w-3 h-3" />
                            Cancel
                          </ConfirmButton>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// Buyers (recorded counterpart)
// =============================================================================

function BuyersTab({
  course,
  stats,
  onAuthError,
  gotoSettings,
}: {
  course: Course;
  stats: CourseStats | null;
  onAuthError: () => void;
  gotoSettings: () => void;
}) {
  const productCode = course.recorded_product_code;
  const [learners, setLearners] = useState<Learner[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  // Grant form
  const [grantEmail, setGrantEmail] = useState('');
  const [grantName, setGrantName] = useState('');
  const [grantNotify, setGrantNotify] = useState(true);

  const note = (m: string) => {
    setFlash(m);
    window.setTimeout(() => setFlash(null), 4000);
  };

  const load = useCallback(async () => {
    if (!productCode) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api<{ learners: Learner[] }>(
        `/api/admin/academy/learners?product_code=${encodeURIComponent(productCode)}`,
      );
      setLearners(res.learners);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [productCode, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!productCode) {
    return (
      <EmptyState
        icon={<GraduationCap className="w-5 h-5" />}
        title="No recorded product linked"
        hint="Link this cohort to its recorded academy product and this tab fills with buyers, revenue, enrollment sources, and access controls."
        action={
          <button onClick={gotoSettings} className="btn-secondary text-sm py-2 px-4">
            Open Settings to link one
          </button>
        }
      />
    );
  }

  const rec = stats?.recorded ?? null;

  const filtered = (learners ?? []).filter((l) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return `${l.email} ${l.full_name}`.toLowerCase().includes(q);
  });

  async function grant(e: React.FormEvent) {
    e.preventDefault();
    if (!grantEmail.trim()) return;
    setBusy('grant');
    setError(null);
    try {
      await api('/api/admin/academy/grant', {
        method: 'POST',
        body: JSON.stringify({
          email: grantEmail.trim(),
          product_code: productCode,
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
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  async function signInLink(email: string) {
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
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  async function revoke(email: string) {
    setBusy(email + productCode);
    setError(null);
    try {
      await api('/api/admin/academy/revoke', {
        method: 'POST',
        body: JSON.stringify({ email, product_code: productCode }),
      });
      note(`Access revoked for ${email}.`);
      await load();
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {/* Revenue KPIs from the linked product */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Kpi label="Orders paid" value={rec ? rec.orders_paid : '—'} accent="cyan" />
        <Kpi label="Revenue total" value={rec ? money(rec.revenue_cents_total) : '—'} accent="emerald" />
        <Kpi label="Revenue 30d" value={rec ? money(rec.revenue_cents_30d) : '—'} accent="emerald" />
        <Kpi label="Active learners" value={rec ? rec.active_enrollments : '—'} accent="cyan" />
        <Kpi label="Completed" value={rec ? rec.learners_completed : '—'} accent="slate" />
      </div>

      {/* Grant access — prefilled with the linked product */}
      <form onSubmit={grant} className="card p-5 grid sm:grid-cols-3 gap-4">
        <div className="sm:col-span-3 flex items-center justify-between">
          <h3 className="font-semibold text-white text-sm">
            Grant free access to <span className="font-mono text-cyan-300">{productCode}</span>
          </h3>
        </div>
        <LabeledInput
          label="Email address"
          type="email"
          required
          value={grantEmail}
          onChange={setGrantEmail}
          placeholder="engineer@company.com"
        />
        <LabeledInput label="Name (optional)" value={grantName} onChange={setGrantName} />
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
      </form>

      {/* Learners on this product */}
      <div>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h3 className="text-sm font-semibold text-white">
            Buyers &amp; learners{learners ? ` (${filtered.length})` : ''}
          </h3>
          <div className="relative ml-auto">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search email or name…"
              className="bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 w-56 max-w-full"
            />
          </div>
          <RefreshButton onClick={() => void load()} loading={loading} small />
        </div>

        <div className="card overflow-x-auto">
          {learners === null && (
            <p className="text-slate-400 text-sm p-5">
              {loading ? 'Loading learners…' : 'Learners will appear here.'}
            </p>
          )}
          {learners !== null && filtered.length === 0 && (
            <p className="text-slate-400 text-sm p-5">
              {learners.length === 0
                ? 'Nobody has access to this product yet — grant someone access above or wait for the first purchase.'
                : 'No learners match the search.'}
            </p>
          )}
          {learners !== null && filtered.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800">
                  <th className="px-4 py-3">Learner</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3">Progress</th>
                  <th className="px-4 py-3">Last seen</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((l) => {
                  const enr = l.enrollments.find(
                    (e) => e.product_code === productCode && e.status === 'active',
                  );
                  return (
                    <tr key={l.id} className="border-b border-slate-800/60 last:border-0">
                      <td className="px-4 py-3">
                        <div className="text-white flex items-center gap-2">
                          {l.email}
                          {l.is_owner && (
                            <span className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
                              OWNER
                            </span>
                          )}
                        </div>
                        {l.full_name && <div className="text-xs text-slate-500">{l.full_name}</div>}
                      </td>
                      <td className="px-4 py-3">
                        {enr ? (
                          <div>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                              {enr.source}
                            </span>
                            <div className="text-[11px] text-slate-500 mt-1">
                              since {formatDate(enr.granted_at)}
                            </div>
                          </div>
                        ) : (
                          <span className="text-slate-500 text-xs">{l.is_owner ? 'owner' : '—'}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs font-mono">
                        {l.lessons_completed} lessons · {l.quiz_attempts} attempts
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
                          {enr && (
                            <ConfirmButton
                              message={`Revoke ${l.email}'s access to ${productCode}?`}
                              onConfirm={() => void revoke(l.email)}
                              disabled={busy === l.email + productCode}
                              className="text-xs text-slate-500 hover:text-amber-300 inline-flex items-center gap-1 disabled:opacity-40"
                              title={`Revoke ${productCode}`}
                            >
                              <Trash2 className="w-3.5 h-3.5" /> Revoke
                            </ConfirmButton>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Comms
// =============================================================================

type LogGroup = {
  ts: string;
  audience: string;
  template: string;
  subject: string;
  total: number;
  ok: number;
  fail: number;
};

function groupLog(rows: EmailLogRow[]): LogGroup[] {
  const map = new Map<string, LogGroup>();
  for (const r of rows) {
    // Batch sends share a timestamp second — bucket to the minute + subject
    // + audience so one broadcast collapses to one row.
    const key = `${r.ts.slice(0, 16)}|${r.subject}|${r.audience}|${r.template}`;
    const g = map.get(key);
    if (g) {
      g.total += 1;
      if (r.ok) g.ok += 1;
      else g.fail += 1;
    } else {
      map.set(key, {
        ts: r.ts,
        audience: r.audience,
        template: r.template,
        subject: r.subject,
        total: 1,
        ok: r.ok ? 1 : 0,
        fail: r.ok ? 0 : 1,
      });
    }
  }
  return [...map.values()];
}

function CommsTab({
  code,
  course,
  stats,
  onAuthError,
}: {
  code: string;
  course: Course;
  stats: CourseStats | null;
  onAuthError: () => void;
}) {
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState(lesson.body ?? '');
  const [rawHtml, setRawHtml] = useState(false);
  const [audience, setAudience] = useState<NotifyAudience>('all');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const [log, setLog] = useState<EmailLogRow[] | null>(null);
  const [logLoading, setLogLoading] = useState(false);

  const loadLog = useCallback(async () => {
    setLogLoading(true);
    try {
      const res = await api<{ rows: EmailLogRow[] }>(
        `/api/admin/comms/log?scope_code=${encodeURIComponent(code)}&limit=400`,
      );
      setLog(res.rows);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLogLoading(false);
    }
  }, [code, onAuthError]);

  useEffect(() => {
    void loadLog();
  }, [loadLog]);

  const pending = Math.max(0, course.seats_taken - course.seats_paid);
  const recordedCount = course.recorded_product_code
    ? (stats?.recorded?.active_enrollments ?? null)
    : 0;

  const audiences: { key: NotifyAudience; label: string; count: number | null; hint?: string }[] = [
    { key: 'all', label: 'All live', count: course.seats_taken, hint: 'paid + pending' },
    { key: 'paid', label: 'Paid', count: course.seats_paid },
    { key: 'pending', label: 'Pending', count: pending },
    {
      key: 'recorded',
      label: 'Recorded buyers',
      count: recordedCount,
      hint: course.recorded_product_code ?? 'no product linked',
    },
    {
      key: 'everyone',
      label: 'Everyone',
      count:
        recordedCount === null ? null : course.seats_taken + recordedCount,
      hint: 'live + recorded, deduped',
    },
  ];

  const selected = audiences.find((a) => a.key === audience)!;
  const countLabel =
    selected.count === null
      ? ''
      : ` (~${selected.count} recipient${selected.count === 1 ? '' : 's'})`;

  async function send() {
    if (!subject.trim() || !body.trim()) {
      setError('Subject and body are required.');
      return;
    }
    if (
      !window.confirm(
        `Send "${subject.trim()}" to ${selected.label}${countLabel} on ${code}?`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const bodyHtml = rawHtml ? body : plainTextToEmailHtml(body);
      const data = await api<NotifyResult>(
        `/api/admin/courses/${encodeURIComponent(code)}/notify`,
        {
          method: 'POST',
          body: JSON.stringify({ subject: subject.trim(), body_html: bodyHtml, audience }),
        },
      );
      setFlash(
        `Broadcast sent to ${data.recipients} recipient${data.recipients === 1 ? '' : 's'}` +
          (data.failures > 0 ? ` (${data.failures} failed)` : '') +
          '.',
      );
      window.setTimeout(() => setFlash(null), 6000);
      setSubject('');
      setBody('');
      void loadLog();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(false);
    }
  }

  const groups = useMemo(() => groupLog(log ?? []), [log]);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
      {/* Composer */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-4">
        <h3 className="text-white font-semibold flex items-center gap-2">
          <Send className="w-4 h-4 text-cyan-300" /> Broadcast to {course.title}
        </h3>

        {flash && <Notice kind="success">{flash}</Notice>}
        {error && <Notice kind="error">{error}</Notice>}

        <div>
          <span className="block text-[11px] uppercase tracking-wider text-slate-300 mb-1">
            Audience
          </span>
          <div className="flex flex-wrap gap-2">
            {audiences.map((a) => (
              <button
                key={a.key}
                type="button"
                onClick={() => setAudience(a.key)}
                title={a.hint}
                className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                  audience === a.key
                    ? 'bg-cyan-500/20 border-cyan-500/60 text-cyan-200'
                    : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-slate-200'
                }`}
              >
                {a.label}
                {a.count !== null && <span className="ml-1 text-slate-400">{a.count}</span>}
              </button>
            ))}
          </div>
          {audience === 'recorded' && !course.recorded_product_code && (
            <p className="text-[11px] text-amber-300 mt-1">
              No recorded product is linked — this audience is empty until one is set in Settings.
            </p>
          )}
        </div>

        <MessageEditor
          subject={subject}
          onSubject={setSubject}
          body={body}
          onBody={setBody}
          rawHtml={rawHtml}
          onRawHtml={setRawHtml}
        />

        <div className="flex items-center justify-end pt-1">
          <button
            onClick={() => void send()}
            disabled={busy || !subject.trim() || !body.trim()}
            className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
            {busy ? 'Sending…' : `Send to ${selected.label.toLowerCase()}${countLabel}`}
          </button>
        </div>
      </div>

      {/* History */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <h3 className="text-white font-semibold text-sm">Email history — {code}</h3>
          <RefreshButton onClick={() => void loadLog()} loading={logLoading} small />
        </div>
        {log === null && (
          <div className="p-6 text-sm text-slate-300">{logLoading ? 'Loading…' : '—'}</div>
        )}
        {log !== null && groups.length === 0 && (
          <div className="p-6 text-sm text-slate-300">
            Nothing sent for this course yet — broadcasts and automated emails will appear here.
          </div>
        )}
        {log !== null && groups.length > 0 && (
          <ul className="divide-y divide-slate-800 max-h-[560px] overflow-y-auto">
            {groups.map((g, i) => (
              <li key={`${g.ts}-${i}`} className="px-5 py-3 text-xs">
                <div className="flex items-center justify-between gap-3 mb-0.5">
                  <span className="text-slate-400 whitespace-nowrap">{formatDate(g.ts)}</span>
                  <span
                    className={`px-2 py-0.5 rounded-full border text-[10px] ${
                      g.fail === 0
                        ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                        : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                    }`}
                  >
                    {g.fail === 0 ? `${g.total} sent` : `${g.ok} ok · ${g.fail} failed`}
                  </span>
                </div>
                <div className="text-slate-200 truncate" title={g.subject}>
                  {g.subject}
                </div>
                <div className="text-[10px] font-mono text-slate-500 mt-0.5">
                  {g.audience || '—'} · {g.template || 'broadcast'}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// Stats
// =============================================================================

function buildLast60(byDay: { date: string; count: number }[]): { label: string; count: number }[] {
  const m = new Map(byDay.map((d) => [d.date, d.count]));
  const out: { label: string; count: number }[] = [];
  const today = new Date();
  for (let i = 59; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    out.push({ label: iso, count: m.get(iso) ?? 0 });
  }
  return out;
}

function StatsTab({ course, stats }: { course: Course; stats: CourseStats | null }) {
  const days = useMemo(() => buildLast60(stats?.live.by_day ?? []), [stats]);

  if (!stats) {
    return (
      <div className="card p-8 text-sm text-slate-300">
        Stats for this course haven't loaded — hit Refresh above.
      </div>
    );
  }

  const total60 = days.reduce((s, d) => s + d.count, 0);

  return (
    <div className="space-y-6">
      {/* Registrations per day */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm font-semibold text-slate-200">Registrations — last 60 days</p>
          <span className="text-xs text-slate-400">{total60} total</span>
        </div>
        {total60 === 0 ? (
          <p className="text-sm text-slate-400">No registrations in the last 60 days.</p>
        ) : (
          <BarChart data={days} height={120} />
        )}
        <div className="flex justify-between text-[10px] text-slate-500 mt-1 font-mono">
          <span>{days[0]?.label}</span>
          <span>{days[days.length - 1]?.label}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By company */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5">
          <p className="text-sm font-semibold text-slate-200 mb-3">Top companies</p>
          <HBarList
            rows={stats.live.by_company.map((c) => ({
              label: c.company || '(unknown)',
              count: c.count,
            }))}
            empty="No registrations yet."
          />
        </div>

        {/* Seats */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5">
          <p className="text-sm font-semibold text-slate-200 mb-3">Seats</p>
          <SeatsBar
            paid={stats.live.paid}
            taken={stats.live.seats_taken}
            total={stats.live.seats_total}
          />
          <div className="grid grid-cols-2 gap-3 mt-4 text-sm">
            <div className="text-slate-300">
              <span className="text-emerald-300 font-semibold">{stats.live.paid}</span> paid
            </div>
            <div className="text-slate-300">
              <span className="text-amber-300 font-semibold">{stats.live.pending}</span> pending
            </div>
            <div className="text-slate-300">
              <span className="text-white font-semibold">
                {Math.max(0, stats.live.seats_total - stats.live.seats_taken)}
              </span>{' '}
              seats free of {stats.live.seats_total}
            </div>
            <div className="text-slate-300">
              <span className="text-slate-400 font-semibold">{stats.live.cancelled}</span> cancelled
            </div>
          </div>
          {course.day_dates.length > 0 && (
            <p className="text-xs text-slate-400 mt-4">
              {course.day_dates.length}-day cohort · {formatDay(course.day_dates[0])} →{' '}
              {formatDay(course.day_dates[course.day_dates.length - 1])}
            </p>
          )}
        </div>
      </div>

      {/* Recorded revenue */}
      {stats.recorded ? (
        <div>
          <p className="text-sm font-semibold text-slate-200 mb-3">
            Recorded counterpart — {course.recorded_product_code}
          </p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Kpi label="Orders paid" value={stats.recorded.orders_paid} accent="cyan" />
            <Kpi label="Revenue total" value={money(stats.recorded.revenue_cents_total)} accent="emerald" />
            <Kpi label="Revenue 30d" value={money(stats.recorded.revenue_cents_30d)} accent="emerald" />
            <Kpi label="Active learners" value={stats.recorded.active_enrollments} accent="cyan" />
            <Kpi label="Completed" value={stats.recorded.learners_completed} accent="slate" />
          </div>
        </div>
      ) : (
        <p className="text-xs text-slate-500">
          No recorded product linked — link one in Settings to see recorded revenue here.
        </p>
      )}
    </div>
  );
}

// =============================================================================
// Materials
// =============================================================================

function MaterialsTab({
  course,
  onAuthError,
  gotoSettings,
}: {
  course: Course;
  onAuthError: () => void;
  gotoSettings: () => void;
}) {
  const productCode = course.recorded_product_code;
  const [content, setContent] = useState<ProductContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [openModules, setOpenModules] = useState<Record<number, boolean>>({});
  const [selected, setSelected] = useState<ContentLesson | null>(null);

  const load = useCallback(async () => {
    if (!productCode) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api<ProductContent>(
        `/api/admin/academy/products/${encodeURIComponent(productCode)}/content`,
      );
      setContent(res);
      setOpenModules((prev) =>
        Object.keys(prev).length > 0 || res.modules.length === 0
          ? prev
          : { [res.modules[0].id]: true },
      );
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [productCode, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!productCode) {
    return (
      <EmptyState
        icon={<PlayCircle className="w-5 h-5" />}
        title="No recorded product linked"
        hint="Once this cohort is linked to its recorded academy product, the module and lesson tree appears here for editing — titles, previews, ordering."
        action={
          <button onClick={gotoSettings} className="btn-secondary text-sm py-2 px-4">
            Open Settings to link one
          </button>
        }
      />
    );
  }

  function lessonSaved(id: number, patch: Partial<ContentLesson>) {
    setContent((prev) =>
      prev
        ? {
            ...prev,
            modules: prev.modules.map((m) => ({
              ...m,
              lessons: m.lessons
                .map((l) => (l.id === id ? { ...l, ...patch } : l))
                .sort((a, b) => a.position - b.position),
            })),
          }
        : prev,
    );
    setFlash('Lesson saved.');
    window.setTimeout(() => setFlash(null), 3000);
  }

  return (
    <div>
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {loading && !content && <div className="card p-8 text-sm text-slate-300">Loading content…</div>}

      {content && content.modules.length === 0 && (
        <div className="card p-8 text-sm text-slate-300">
          The linked product <span className="font-mono">{productCode}</span> has no modules yet.
        </div>
      )}

      {content && content.modules.length > 0 && (
        <div className="space-y-3">
          {content.modules.map((m) => {
            const open = !!openModules[m.id];
            const pendingVideos = m.lessons.filter(
              (l) => l.kind === 'video' && !l.video_uid,
            ).length;
            return (
              <div key={m.id} className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
                <button
                  onClick={() => setOpenModules((prev) => ({ ...prev, [m.id]: !open }))}
                  className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-slate-800/30"
                >
                  <span className="text-xs font-mono text-slate-500 w-6 shrink-0">{m.position}</span>
                  <span className="text-white font-medium flex-1 min-w-0 truncate">{m.title}</span>
                  <span className="text-xs text-slate-400 hidden sm:inline whitespace-nowrap">
                    {m.lessons.length} lessons · {m.hours} hrs
                    {m.quiz_item_count > 0 && <> · {m.quiz_item_count} quiz items</>}
                  </span>
                  {pendingVideos > 0 && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/40 text-amber-300 whitespace-nowrap">
                      {pendingVideos} videos pending
                    </span>
                  )}
                  <span className="text-slate-500 text-xs">{open ? '▾' : '▸'}</span>
                </button>
                {open && (
                  <ul className="divide-y divide-slate-800/60 border-t border-slate-800">
                    {m.lessons.map((l) => (
                      <li key={l.id}>
                        <button
                          onClick={() => setSelected(l)}
                          className="w-full flex items-center gap-3 px-5 py-2.5 text-left text-sm hover:bg-slate-800/40"
                        >
                          <span className="text-slate-500 shrink-0">
                            {l.kind === 'video' ? (
                              <PlayCircle className="w-4 h-4" />
                            ) : l.kind === 'quiz' ? (
                              <HelpCircle className="w-4 h-4" />
                            ) : (
                              <FileText className="w-4 h-4" />
                            )}
                          </span>
                          <span
                            className={`w-2 h-2 rounded-full shrink-0 ${
                              l.kind !== 'video'
                                ? 'bg-slate-600'
                                : l.video_uid
                                  ? 'bg-emerald-400'
                                  : 'bg-amber-400'
                            }`}
                            title={
                              l.kind !== 'video'
                                ? l.kind
                                : l.video_uid
                                  ? 'video uploaded'
                                  : 'video pending'
                            }
                          />
                          <span className="text-slate-200 flex-1 min-w-0 truncate">{l.title}</span>
                          {l.is_preview && (
                            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
                              <Eye className="w-3 h-3" /> preview
                            </span>
                          )}
                          {l.duration_s > 0 && (
                            <span className="text-xs text-slate-500 font-mono whitespace-nowrap">
                              {fmtDuration(l.duration_s)}
                            </span>
                          )}
                        </button>
                      </li>
                    ))}
                    {m.lessons.length === 0 && (
                      <li className="px-5 py-3 text-xs text-slate-500">No lessons in this module.</li>
                    )}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}

      {selected && (
        <LessonEditor
          lesson={selected}
          onClose={() => setSelected(null)}
          onSaved={(patch) => {
            lessonSaved(selected.id, patch);
            setSelected(null);
          }}
          onAuthError={onAuthError}
        />
      )}
    </div>
  );
}

function LessonEditor({
  lesson,
  onClose,
  onSaved,
  onAuthError,
}: {
  lesson: ContentLesson;
  onClose: () => void;
  onSaved: (patch: Partial<ContentLesson>) => void;
  onAuthError: () => void;
}) {
  const [title, setTitle] = useState(lesson.title);
  const [isPreview, setIsPreview] = useState(lesson.is_preview);
  const [position, setPosition] = useState(String(lesson.position));
  const [body, setBody] = useState(lesson.body ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const patch: Record<string, unknown> = {};
    if (title.trim() && title.trim() !== lesson.title) patch.title = title.trim();
    if (isPreview !== lesson.is_preview) patch.is_preview = isPreview;
    const pos = parseInt(position, 10);
    if (!Number.isNaN(pos) && pos !== lesson.position) patch.position = pos;
    if (body !== (lesson.body ?? '')) patch.body = body;
    if (Object.keys(patch).length === 0) {
      onClose();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api(`/api/admin/academy/lessons/${lesson.id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      });
      const uiPatch: Partial<ContentLesson> = {};
      if (patch.title) uiPatch.title = title.trim();
      if (patch.body !== undefined) uiPatch.body = body;
      if (patch.is_preview !== undefined) uiPatch.is_preview = isPreview;
      if (patch.position !== undefined) uiPatch.position = pos;
      onSaved(uiPatch);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} aria-hidden />
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-slate-900 border-l border-slate-800 shadow-2xl overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800 sticky top-0 bg-slate-900">
          <div className="min-w-0">
            <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
              {lesson.kind} · {lesson.code}
            </div>
            <h3 className="text-white font-semibold truncate">Edit lesson</h3>
          </div>
          <button onClick={onClose} className="text-slate-300 hover:text-white" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {error && <Notice kind="error">{error}</Notice>}

          <LabeledInput label="Title" value={title} onChange={setTitle} />

          <div className="grid grid-cols-2 gap-3">
            <LabeledInput
              label="Position"
              type="number"
              min={0}
              value={position}
              onChange={setPosition}
            />
            <label className="flex items-end gap-2 text-sm text-slate-300 pb-2">
              <input
                type="checkbox"
                checked={isPreview}
                onChange={(e) => setIsPreview(e.target.checked)}
                className="accent-cyan-400"
              />
              Free preview lesson
            </label>
          </div>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-300 block mb-1">
              Body (notes shown under the lesson)
            </span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={8}
              placeholder="Lesson body (markdown/plain text)."
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            />
            <span className="text-[11px] text-slate-500 mt-1 block">
              The existing body isn't returned by the API, so it isn't shown here. Typing anything
              replaces it; leaving this blank keeps it as-is.
            </span>
          </label>

          <div className="text-xs text-slate-500 space-y-1 border-t border-slate-800 pt-3">
            <div>
              Video:{' '}
              {lesson.kind !== 'video' ? (
                <span className="text-slate-400">n/a ({lesson.kind})</span>
              ) : lesson.video_uid ? (
                <span className="text-emerald-300 font-mono">{lesson.video_uid}</span>
              ) : (
                <span className="text-amber-300">not uploaded yet</span>
              )}
            </div>
            {lesson.duration_s > 0 && <div>Duration: {fmtDuration(lesson.duration_s)}</div>}
            {lesson.source_file && <div className="truncate">Source: {lesson.source_file}</div>}
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button onClick={onClose} className="text-sm text-slate-300 hover:text-white px-3 py-1.5">
              Cancel
            </button>
            <button
              onClick={() => void save()}
              disabled={saving}
              className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// =============================================================================
// Settings
// =============================================================================

function SettingsTab({
  course,
  products,
  onSaved,
  onAuthError,
}: {
  course: Course;
  products: AcademyProduct[] | null;
  onSaved: (c: Course) => void;
  onAuthError: () => void;
}) {
  const [title, setTitle] = useState(course.title);
  const [startDate, setStartDate] = useState(course.start_date);
  const [seatsText, setSeatsText] = useState(String(course.total_seats));
  const [dayDates, setDayDates] = useState<string[]>(course.day_dates);
  const [priceText, setPriceText] = useState(String(course.price_cents / 100));
  const [currency, setCurrency] = useState(course.currency || 'usd');
  const [recorded, setRecorded] = useState(course.recorded_product_code ?? '');
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const parsedSeats = parseInt(seatsText, 10);
  const parsedPriceCents = Math.round((parseFloat(priceText) || 0) * 100);

  const patch: CoursePatch = {};
  if (title.trim() && title.trim() !== course.title) patch.title = title.trim();
  if (startDate && startDate !== course.start_date) patch.start_date = startDate;
  if (!Number.isNaN(parsedSeats) && parsedSeats !== course.total_seats)
    patch.total_seats = parsedSeats;
  if (JSON.stringify(dayDates) !== JSON.stringify(course.day_dates)) patch.day_dates = dayDates;
  if (parsedPriceCents !== course.price_cents) patch.price_cents = parsedPriceCents;
  if (currency !== (course.currency || 'usd')) patch.currency = currency;
  if (recorded !== (course.recorded_product_code ?? ''))
    patch.recorded_product_code = recorded || null;

  const dirty = Object.keys(patch).length > 0;

  function applySaved(c: Course) {
    onSaved(c);
    setTitle(c.title);
    setStartDate(c.start_date);
    setSeatsText(String(c.total_seats));
    setDayDates(c.day_dates);
    setPriceText(String(c.price_cents / 100));
    setCurrency(c.currency || 'usd');
    setRecorded(c.recorded_product_code ?? '');
  }

  async function save() {
    if (!dirty) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api<Course>(`/api/admin/courses/${encodeURIComponent(course.code)}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      });
      applySaved(updated);
      setFlash(
        patch.start_date
          ? `Saved ${course.code}. Registrants notified of the new start date.`
          : `Saved ${course.code}.`,
      );
      window.setTimeout(() => setFlash(null), 4000);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus() {
    const next: 'open' | 'closed' = course.status === 'open' ? 'closed' : 'open';
    setToggling(true);
    setError(null);
    try {
      const updated = await api<Course>(`/api/admin/courses/${encodeURIComponent(course.code)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: next }),
      });
      onSaved(updated);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className="max-w-3xl">
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-5">
        <div className="flex items-center justify-between">
          <h3 className="text-white font-semibold">Course settings</h3>
          <button
            onClick={() => void toggleStatus()}
            disabled={toggling}
            className={`inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md border disabled:opacity-50 ${
              course.status === 'open'
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-200'
                : 'bg-slate-800/60 border-slate-700 text-slate-300'
            }`}
            title="Toggles immediately — open courses accept registrations"
          >
            {course.status === 'open' ? (
              <>
                <Unlock className="w-3 h-3" /> Open
              </>
            ) : (
              <>
                <Lock className="w-3 h-3" /> Closed
              </>
            )}
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <LabeledInput label="Title" value={title} onChange={setTitle} />
          <LabeledInput
            label="Start date"
            type="date"
            value={startDate}
            onChange={setStartDate}
            icon={<Calendar className="w-3 h-3 text-slate-300" />}
          />
          <LabeledInput
            label="Total seats"
            type="number"
            min={1}
            value={seatsText}
            onChange={setSeatsText}
          />
        </div>

        <DayDatesEditor value={dayDates} startDate={startDate} onChange={setDayDates} />

        {/* Pricing */}
        <div className="border-t border-slate-800 pt-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <LabeledInput
              label={`Seat price (${currency.toUpperCase()})`}
              type="number"
              min={0}
              step="0.01"
              value={priceText}
              onChange={setPriceText}
            />
            <LabeledSelect label="Currency" value={currency} onChange={setCurrency}>
              <option value="usd">USD</option>
              <option value="eur">EUR</option>
              <option value="sar">SAR</option>
            </LabeledSelect>
            <LabeledSelect
              label="Recorded product"
              value={recorded}
              onChange={setRecorded}
              disabled={products === null}
            >
              <option value="">— none —</option>
              {(products ?? []).map((p) => (
                <option key={p.code} value={p.code}>
                  {p.title} ({p.code})
                </option>
              ))}
            </LabeledSelect>
          </div>
          <p className="text-[11px] text-slate-400 mt-2">
            Price 0 keeps the cohort invoice-only (no PayPal/Stripe checkout on the public page).
            Linking a recorded product unlocks the Buyers and Materials tabs plus the "Recorded
            buyers" email audience.
          </p>
        </div>

        {dirty && (
          <div className="flex items-center justify-between gap-3 text-xs text-amber-200 bg-amber-950/40 border border-amber-900/60 rounded-lg px-3 py-2">
            <span>
              {patch.start_date
                ? 'Saving will email all registrants about the new start date.'
                : 'Unsaved changes.'}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => applySaved(course)}
                className="text-slate-300 hover:text-white"
              >
                Discard
              </button>
              <button
                onClick={() => void save()}
                disabled={saving}
                className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md bg-cyan-500 hover:bg-cyan-400 text-slate-950 disabled:opacity-50"
              >
                <Save className="w-3 h-3" />
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DayDatesEditor({
  value,
  startDate,
  onChange,
}: {
  value: string[];
  startDate: string;
  onChange: (v: string[]) => void;
}) {
  const setDayDate = (i: number, iso: string) => {
    const next = [...value];
    next[i] = iso;
    onChange(next);
  };
  const addDay = () => {
    // Default new day to one day after the last entry, or to start_date.
    const last = value[value.length - 1] ?? startDate;
    let next = last;
    try {
      const d = new Date(`${last}T00:00:00`);
      d.setDate(d.getDate() + 1);
      next = d.toISOString().slice(0, 10);
    } catch {
      /* keep last */
    }
    onChange([...value, next]);
  };
  const removeDay = (i: number) => {
    onChange(value.filter((_, idx) => idx !== i));
  };

  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-slate-300 flex items-center gap-1 mb-2">
        <Calendar className="w-3 h-3 text-slate-300" />
        Day-by-day schedule
        <span className="ml-2 text-slate-300 normal-case tracking-normal">
          ({value.length} {value.length === 1 ? 'day' : 'days'})
        </span>
      </div>
      {value.length === 0 ? (
        <div className="text-xs text-slate-300 italic mb-2">
          No days scheduled. Click "Add day" to start.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {value.map((iso, i) => (
            <div
              key={i}
              className="flex items-center gap-2 bg-slate-950/60 border border-slate-800 rounded-lg px-2 py-1.5"
            >
              <span className="text-[11px] font-mono text-slate-300 w-12 shrink-0">Day {i + 1}</span>
              <input
                type="date"
                value={iso}
                onChange={(e) => setDayDate(i, e.target.value)}
                className="flex-1 min-w-0 bg-transparent border-0 text-sm text-white focus:outline-none"
              />
              <button
                type="button"
                onClick={() => removeDay(i)}
                title="Remove this day"
                className="text-slate-300 hover:text-red-300 text-xs px-1"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={addDay}
        className="mt-2 inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md border border-slate-700 bg-slate-800/40 text-slate-200 hover:bg-slate-800"
      >
        <Plus className="w-3 h-3" />
        Add day
      </button>
    </div>
  );
}
