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
  Award,
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
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Unlock,
  UserCheck,
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
  formatShortDate,
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
  SettlementBadge,
  StatusBadge,
} from './ui';
import CertificationTab from './CertificationTab';

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
  { key: 'access', label: 'Access', icon: <Lock className="w-4 h-4" /> },
  { key: 'integrity', label: 'Integrity', icon: <ShieldAlert className="w-4 h-4" /> },
  { key: 'comms', label: 'Comms', icon: <Mail className="w-4 h-4" /> },
  { key: 'stats', label: 'Stats', icon: <BarChart3 className="w-4 h-4" /> },
  { key: 'materials', label: 'Materials', icon: <PlayCircle className="w-4 h-4" /> },
  { key: 'certification', label: 'Certification', icon: <Award className="w-4 h-4" /> },
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
      {course && tab === 'access' && (
        <AccessTab
          course={course}
          onAuthError={onAuthError}
          gotoSettings={() => onTab('settings')}
        />
      )}
      {course && tab === 'integrity' && (
        <IntegrityTab
          course={course}
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
      {course && tab === 'certification' && (
        <CertificationTab
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
  // 'unconfirmed' is not a registration status — it is the chase list: who
  // still hasn't answered the confirm-your-seat email.
  const [statusFilter, setStatusFilter] = useState<
    'all' | 'pending' | 'paid' | 'cancelled' | 'unconfirmed'
  >('all');

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
    // confirmed/unconfirmed count ACTIVE rows only — someone who cancelled
    // isn't outstanding, so counting them would inflate the chase list.
    const c = { pending: 0, paid: 0, cancelled: 0, total: 0, confirmed: 0, unconfirmed: 0 };
    for (const r of regs ?? []) {
      c.total += 1;
      if (r.status === 'pending') c.pending += 1;
      else if (r.status === 'paid') c.paid += 1;
      else if (r.status === 'cancelled') c.cancelled += 1;
      if (r.status !== 'cancelled') {
        if (r.attendance_confirmed_at) c.confirmed += 1;
        else c.unconfirmed += 1;
      }
    }
    return c;
  }, [regs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (regs ?? []).filter((r) => {
      if (statusFilter === 'unconfirmed') {
        if (r.status === 'cancelled' || r.attendance_confirmed_at) return false;
      } else if (statusFilter !== 'all' && r.status !== statusFilter) {
        return false;
      }
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

  /** Record a confirmation that arrived off-email (a call, a different address). */
  async function setAttendance(id: number, confirmed: boolean) {
    setBusyId(id);
    setError(null);
    try {
      const body = await api<{ ok: boolean; taken: number; registration: Registration }>(
        '/api/admin/attendance',
        { method: 'POST', body: JSON.stringify({ registration_id: id, confirmed }) },
      );
      setRegs((prev) =>
        prev ? prev.map((r) => (r.id === body.registration.id ? body.registration : r)) : prev,
      );
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
        'Attendance confirmed at',
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
        r.attendance_confirmed_at ?? '',
      ]),
    );
  }

  return (
    <div>
      {/* KPI row for this course */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <Kpi
          icon={<Users className="w-4 h-4" />}
          label="Seats"
          value={`${course.seats_taken} / ${course.total_seats}`}
          sub={`${course.seats_remaining} remaining`}
          accent="cyan"
        />
        <Kpi icon={<Clock className="w-4 h-4" />} label="Pending" value={counts.pending} accent="amber" />
        <Kpi icon={<CheckCircle2 className="w-4 h-4" />} label="Paid" value={counts.paid} accent="emerald" />
        {/* Attendance is the answer to "who actually replied to the confirm-your-seat
            email" — it updates by itself when a reply lands in the support desk. */}
        <Kpi
          icon={<UserCheck className="w-4 h-4" />}
          label="Confirmed"
          value={`${counts.confirmed} / ${counts.confirmed + counts.unconfirmed}`}
          sub={counts.unconfirmed > 0 ? `${counts.unconfirmed} awaiting reply` : 'everyone replied'}
          accent={counts.unconfirmed > 0 ? 'amber' : 'emerald'}
        />
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
        {(['all', 'pending', 'paid', 'cancelled', 'unconfirmed'] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            title={
              s === 'unconfirmed'
                ? "Active registrants who haven't confirmed attendance yet"
                : undefined
            }
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
                  <th className="text-left px-4 py-3">Attendance</th>
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
                        <div
                          className="text-[11px] text-slate-300 mt-1"
                          title={formatDate(r.paid_at)}
                        >
                          paid {formatShortDate(r.paid_at)}
                        </div>
                      )}
                    </td>
                    {/* Attendance. Set automatically when the registrant replies to
                        the confirm-your-seat email (the support desk records it on
                        the way in), or by hand here when they answer some other way. */}
                    <td className="px-4 py-3 align-top">
                      {r.status === 'cancelled' ? (
                        <span className="text-xs text-slate-500">—</span>
                      ) : r.attendance_confirmed_at ? (
                        <div>
                          <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 text-emerald-200">
                            <UserCheck className="w-3 h-3" />
                            Confirmed
                          </span>
                          <div
                            className="text-[11px] text-slate-300 mt-1"
                            title={formatDate(r.attendance_confirmed_at)}
                          >
                            {formatShortDate(r.attendance_confirmed_at)}
                          </div>
                          <button
                            onClick={() => void setAttendance(r.id, false)}
                            disabled={busyId === r.id}
                            title="Recorded against the wrong person? Clear it."
                            className="text-[11px] text-slate-400 hover:text-slate-200 underline mt-0.5 disabled:opacity-50"
                          >
                            undo
                          </button>
                        </div>
                      ) : (
                        <div>
                          <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-200">
                            <Clock className="w-3 h-3" />
                            Awaiting reply
                          </span>
                          <button
                            onClick={() => void setAttendance(r.id, true)}
                            disabled={busyId === r.id}
                            title="They confirmed some other way (a call, a different address)"
                            className="block text-[11px] text-cyan-300 hover:text-cyan-200 underline mt-1 disabled:opacity-50"
                          >
                            mark confirmed
                          </button>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <ProviderBadge provider={r.payment_provider} />
                    </td>
                    <td
                      className="px-4 py-3 align-top text-slate-300 text-xs whitespace-nowrap"
                      title={formatDate(r.created_at)}
                    >
                      {formatShortDate(r.created_at)}
                    </td>
                    <td className="px-4 py-3 align-top">
                      {/* Stacked, not side by side: at this column width the
                          labels wrapped mid-word and the pair drifted out from
                          under the Actions header. A fixed width keeps the two
                          aligned even on rows where only one of them renders. */}
                      <div className="flex flex-col items-end gap-1.5">
                        {r.status !== 'cancelled' && (
                          <ConfirmButton
                            message={`Cancel ${r.full_name}'s registration? The seat will be released.`}
                            onConfirm={() => void action('cancel', r.id)}
                            disabled={busyId === r.id}
                            className="inline-flex items-center justify-center gap-1 whitespace-nowrap w-28 text-xs px-2 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 disabled:opacity-50"
                          >
                            <XCircle className="w-3 h-3" />
                            Cancel
                          </ConfirmButton>
                        )}
                        {r.status !== 'paid' && (
                          <ConfirmButton
                            message={`Mark ${r.full_name} (${r.email}) as paid?`}
                            onConfirm={() => void action('mark-paid', r.id)}
                            disabled={busyId === r.id}
                            className="inline-flex items-center justify-center gap-1 whitespace-nowrap w-28 text-xs px-2 py-1 rounded-md bg-emerald-600/90 hover:bg-emerald-500 text-white disabled:opacity-50"
                          >
                            <CheckCircle2 className="w-3 h-3" />
                            Mark paid
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

/* ---------------------------------------------------------------------------
 * Access tab — per-day / per-element grants for the linked materials product.
 *
 * The rule it administers: full enrollment ("All") = everything, written
 * automatically when a registration is marked paid; module grants open
 * exactly one day or element each. Toggles act immediately.
 * ------------------------------------------------------------------------- */

type AccessMatrix = {
  product: { code: string; title: string; sequential_gate: boolean };
  modules: { id: number; code: string; title: string; position: number }[];
  learners: {
    learner_id: number;
    email: string;
    full_name: string;
    is_owner: boolean;
    enrolled_all: boolean;
    module_ids: number[];
  }[];
};

function AccessTab({
  course,
  onAuthError,
  gotoSettings,
}: {
  course: Course;
  onAuthError: () => void;
  gotoSettings: () => void;
}) {
  const productCode = course.recorded_product_code;
  const [matrix, setMatrix] = useState<AccessMatrix | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [addEmail, setAddEmail] = useState('');
  const [addName, setAddName] = useState('');
  const [addScope, setAddScope] = useState('all');
  const [addNotify, setAddNotify] = useState(true);

  const note = (m: string) => {
    setFlash(m);
    window.setTimeout(() => setFlash(null), 4000);
  };

  const load = useCallback(async () => {
    if (!productCode) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api<AccessMatrix>(
        `/api/admin/academy/products/${encodeURIComponent(productCode)}/access`,
      );
      setMatrix(res);
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
        icon={<Lock className="w-5 h-5" />}
        title="No materials product linked"
        hint="Link this cohort to its course-materials product in Settings, and this tab becomes the per-day / per-element access panel."
        action={
          <button onClick={gotoSettings} className="btn-secondary text-sm py-2 px-4">
            Open Settings to link one
          </button>
        }
      />
    );
  }

  async function toggleAll(row: AccessMatrix['learners'][number]) {
    setBusy(`all-${row.email}`);
    setError(null);
    try {
      if (row.enrolled_all) {
        await api('/api/admin/academy/revoke', {
          method: 'POST',
          body: JSON.stringify({ email: row.email, product_code: productCode }),
        });
        note(`Full access revoked for ${row.email}. Their per-day grants (if any) still apply.`);
      } else {
        await api('/api/admin/academy/grant', {
          method: 'POST',
          body: JSON.stringify({
            email: row.email,
            product_code: productCode,
            send_email_invite: false,
          }),
        });
        note(`${row.email} now has access to everything.`);
      }
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  async function toggleModule(
    row: AccessMatrix['learners'][number],
    moduleId: number,
    has: boolean,
  ) {
    setBusy(`${row.email}-${moduleId}`);
    setError(null);
    try {
      await api(has ? '/api/admin/academy/revoke-module' : '/api/admin/academy/grant-module', {
        method: 'POST',
        body: JSON.stringify({ email: row.email, module_id: moduleId }),
      });
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  async function addPerson(e: React.FormEvent) {
    e.preventDefault();
    const email = addEmail.trim();
    if (!email || !matrix) return;
    setBusy('add');
    setError(null);
    try {
      if (addScope === 'all') {
        await api('/api/admin/academy/grant', {
          method: 'POST',
          body: JSON.stringify({
            email,
            product_code: productCode,
            full_name: addName.trim(),
            send_email_invite: addNotify,
          }),
        });
      } else {
        await api('/api/admin/academy/grant-module', {
          method: 'POST',
          body: JSON.stringify({
            email,
            module_id: Number(addScope),
            full_name: addName.trim(),
          }),
        });
        if (addNotify) {
          await api('/api/admin/academy/login-link', {
            method: 'POST',
            body: JSON.stringify({ email, send_email: true }),
          });
        }
      }
      note(`${email} added${addNotify ? ' and emailed a sign-in link' : ''}.`);
      setAddEmail('');
      setAddName('');
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

  const modules = matrix?.modules ?? [];

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-300">
        <p>
          <span className="font-semibold text-white">How access works:</span>{' '}
          marking a registration <span className="text-cyan-300">paid</span> grants{' '}
          <span className="font-semibold">everything</span> automatically (and emails a sign-in
          link). Use the toggles here to hand out or pull back individual days or the simulator,
          or the <span className="font-semibold">All</span> column for everything at once.
          Cancelling a paid registration pulls its automatic grant back.
        </p>
      </div>

      <form
        onSubmit={addPerson}
        className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4"
      >
        <div className="flex-1 min-w-[14rem]">
          <label className="block text-xs text-slate-400 mb-1">Email</label>
          <input
            value={addEmail}
            onChange={(e) => setAddEmail(e.target.value)}
            type="email"
            required
            placeholder="student@company.com"
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none text-sm"
          />
        </div>
        <div className="flex-1 min-w-[10rem]">
          <label className="block text-xs text-slate-400 mb-1">Name (optional)</label>
          <input
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
            placeholder="Full name"
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Give</label>
          <select
            value={addScope}
            onChange={(e) => setAddScope(e.target.value)}
            className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-white text-sm focus:border-cyan-500 focus:outline-none"
          >
            <option value="all">Everything</option>
            {modules.map((m) => (
              <option key={m.id} value={String(m.id)}>
                {m.title}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400 pb-2">
          <input
            type="checkbox"
            checked={addNotify}
            onChange={(e) => setAddNotify(e.target.checked)}
            className="accent-cyan-500"
          />
          Email sign-in link
        </label>
        <button type="submit" disabled={busy === 'add'} className="btn-primary text-sm py-2 px-4 disabled:opacity-50">
          {busy === 'add' ? 'Adding…' : 'Add person'}
        </button>
      </form>

      {flash && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-4 py-2 text-sm text-cyan-200">
          {flash}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">
          {error}
        </div>
      )}

      {loading && !matrix ? (
        <div className="py-16 text-center text-slate-400">
          <Loader2 className="w-5 h-5 animate-spin inline-block" />
        </div>
      ) : matrix && matrix.learners.length === 0 ? (
        <EmptyState
          icon={<Users className="w-5 h-5" />}
          title="Nobody has materials access yet"
          hint="Mark a registration paid (Registrations tab) or add someone above."
        />
      ) : matrix ? (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-900/60 text-left text-xs uppercase tracking-wider text-slate-400">
                <th className="px-4 py-3">Learner</th>
                <th className="px-3 py-3 text-center">All</th>
                {modules.map((m) => (
                  <th key={m.id} className="px-3 py-3 text-center whitespace-nowrap" title={m.title}>
                    {m.code}
                  </th>
                ))}
                <th className="px-3 py-3 text-right">Sign-in</th>
              </tr>
            </thead>
            <tbody>
              {matrix.learners.map((row) => (
                <tr key={row.learner_id} className="border-t border-slate-800/70">
                  <td className="px-4 py-3">
                    <div className="text-white">{row.email}</div>
                    <div className="text-xs text-slate-500">
                      {row.full_name}
                      {row.is_owner && (
                        <span className="ml-2 text-[10px] font-mono px-1 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
                          OWNER
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-center">
                    <button
                      type="button"
                      disabled={busy === `all-${row.email}` || row.is_owner}
                      onClick={() => toggleAll(row)}
                      title={
                        row.is_owner
                          ? 'Owner accounts always see everything'
                          : row.enrolled_all
                            ? 'Revoke full access'
                            : 'Grant full access'
                      }
                      className={`w-9 h-7 rounded-md border text-xs font-semibold transition-colors disabled:opacity-40 ${
                        row.enrolled_all || row.is_owner
                          ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300'
                          : 'bg-slate-900 border-slate-700 text-slate-500 hover:border-cyan-500/50'
                      }`}
                    >
                      {row.enrolled_all || row.is_owner ? '✓' : '—'}
                    </button>
                  </td>
                  {modules.map((m) => {
                    const has = row.module_ids.includes(m.id);
                    const covered = row.enrolled_all || row.is_owner;
                    return (
                      <td key={m.id} className="px-3 py-3 text-center">
                        <button
                          type="button"
                          disabled={covered || busy === `${row.email}-${m.id}`}
                          onClick={() => toggleModule(row, m.id, has)}
                          title={
                            covered
                              ? 'Covered by full access'
                              : has
                                ? `Revoke ${m.title}`
                                : `Grant ${m.title}`
                          }
                          className={`w-9 h-7 rounded-md border text-xs font-semibold transition-colors disabled:opacity-40 ${
                            covered
                              ? 'bg-slate-800/60 border-slate-700 text-slate-500'
                              : has
                                ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300'
                                : 'bg-slate-900 border-slate-700 text-slate-500 hover:border-cyan-500/50'
                          }`}
                        >
                          {covered ? '·' : has ? '✓' : '—'}
                        </button>
                      </td>
                    );
                  })}
                  <td className="px-3 py-3 text-right">
                    <button
                      type="button"
                      disabled={busy === 'link' + row.email}
                      onClick={() => signInLink(row.email)}
                      className="btn-secondary text-xs py-1.5 px-3 disabled:opacity-50"
                    >
                      Copy link
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

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
                  // Failed bank payments arrive revoked — resolve them too so
                  // the row badges red instead of reading as never-enrolled.
                  const enr =
                    l.enrollments.find(
                      (e) => e.product_code === productCode && e.status === 'active',
                    ) ??
                    l.enrollments.find(
                      (e) =>
                        e.product_code === productCode && e.settlement_status === 'failed',
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
                            <span className="inline-flex items-center gap-1.5">
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                                {enr.source}
                              </span>
                              <SettlementBadge
                                status={enr.settlement_status}
                                deadline={enr.settlement_deadline}
                              />
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
                          {enr && enr.status === 'active' && (
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
  const [body, setBody] = useState('');
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

// ---------------------------------------------------------------------------
// Integrity — trace a leaked copy, and see the copies that called home
// ---------------------------------------------------------------------------

type Delivery = {
  token: string;
  email: string;
  full_name: string;
  asset_key: string;
  served_at: string | null;
  ip: string;
  user_agent: string;
  ping_count: number;
  worst_status: string;
  downloads_by_this_account?: number;
  pings?: Ping[];
};

type Ping = {
  id: number;
  token: string;
  status: string;
  seen_at: string | null;
  page_url: string;
  origin: string;
  ip: string;
  user_agent: string;
  timezone: string;
  session_email: string;
  issued_to?: string;
  issued_at?: string | null;
  issued_ip?: string;
  asset_key?: string;
  reviewed_at?: string | null;
};

type SharingDevice = {
  user_agent: string;
  ip: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
};

type SharingRow = {
  learner_id: number;
  email: string;
  severity: 'high' | 'warn';
  reasons: string[];
  devices_30d: number;
  devices_total: number;
  distinct_ips_30d: number;
  overlap_7d: number;
  overlap_30d: number;
  last_overlap_at: string | null;
  last_seen_at: string | null;
  devices: SharingDevice[];
};

type IntegrityReport = {
  totals: {
    downloads: number;
    accounts: number;
    alerts: number;
    sharing_flagged?: number;
    sharing_tracked?: number;
  };
  alerts: Ping[];
  watch: {
    learner_id: number;
    email: string;
    downloads: number;
    distinct_ips: number;
    distinct_agents: number;
    alerts: number;
    last_at: string | null;
    reasons: string[];
  }[];
  sharing?: SharingRow[];
  recent: Delivery[];
};

type TraceResult = {
  verdict: 'traced' | 'no-id-found' | 'id-not-issued-by-us';
  tokens_found: string[];
  matches: Delivery[];
  unknown_tokens: string[];
};

/** Plain-English meaning of a call-home status. */
const PING_MEANING: Record<string, { label: string; blurb: string; tone: string }> = {
  offsite: {
    label: 'Opened off your site',
    blurb:
      'This copy was opened from a hard drive or another website. It is not on ' +
      'proreadyengineer.com any more — this is a leak, not a maybe.',
    tone: 'text-rose-300 border-rose-500/40 bg-rose-500/10',
  },
  other_account: {
    label: 'Opened by a different account',
    blurb:
      'The person who opened this copy was signed in as somebody else. The file ' +
      'was passed from the account it was issued to, to this one.',
    tone: 'text-amber-300 border-amber-500/40 bg-amber-500/10',
  },
  unknown_token: {
    label: 'Edited or very old copy',
    blurb:
      'A copy called home with an id you never issued — usually a file whose id ' +
      'was tampered with, or one from before this tracking existed.',
    tone: 'text-amber-300 border-amber-500/40 bg-amber-500/10',
  },
  anonymous: {
    label: 'Nobody signed in',
    blurb:
      'Opened on your site but with no active session — usually just an expired ' +
      'login. Worth a glance, not an alarm.',
    tone: 'text-slate-300 border-slate-600 bg-slate-800/60',
  },
  ok: {
    label: 'Normal use',
    blurb: 'Your site, the right account. Nothing to do.',
    tone: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10',
  },
};

function when(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function browserOf(ua: string): string {
  if (!ua) return '—';
  const os = /Windows/.test(ua) ? 'Windows'
    : /Mac OS X|Macintosh/.test(ua) ? 'Mac'
    : /Android/.test(ua) ? 'Android'
    : /iPhone|iPad/.test(ua) ? 'iOS'
    : /Linux/.test(ua) ? 'Linux' : '';
  const br = /Edg\//.test(ua) ? 'Edge'
    : /OPR\//.test(ua) ? 'Opera'
    : /Chrome\//.test(ua) ? 'Chrome'
    : /Firefox\//.test(ua) ? 'Firefox'
    : /Safari\//.test(ua) ? 'Safari' : 'Browser';
  return [br, os].filter(Boolean).join(' · ');
}

function IntegrityTab({
  course,
  onAuthError,
  gotoSettings,
}: {
  course: Course;
  onAuthError: () => void;
  gotoSettings: () => void;
}) {
  const productCode = course.recorded_product_code;
  const [report, setReport] = useState<IntegrityReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paste, setPaste] = useState('');
  const [tracing, setTracing] = useState(false);
  const [trace, setTrace] = useState<TraceResult | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [showReviewed, setShowReviewed] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!productCode) return;
    setLoading(true);
    setError(null);
    try {
      setReport(
        await api<IntegrityReport>(
          `/api/admin/academy/integrity?product_code=${encodeURIComponent(productCode)}` +
            (showReviewed ? '&include_reviewed=true' : ''),
        ),
      );
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [productCode, onAuthError, showReviewed]);

  useEffect(() => {
    void load();
  }, [load]);

  async function dismiss(pingId: number) {
    setBusy(pingId);
    try {
      await api('/api/admin/academy/integrity/dismiss', {
        method: 'POST',
        body: JSON.stringify({ ping_ids: [pingId] }),
      });
      await load();
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  async function runTrace(content: string) {
    if (!content.trim()) return;
    setTracing(true);
    setError(null);
    setTrace(null);
    try {
      setTrace(
        await api<TraceResult>('/api/admin/academy/integrity/trace', {
          method: 'POST',
          body: JSON.stringify({ content: content.slice(0, 3_500_000) }),
        }),
      );
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setTracing(false);
    }
  }

  async function traceFile(file: File) {
    const text = await file.text();
    setPaste(`${file.name} — ${(file.size / 1024).toFixed(0)} KB`);
    await runTrace(text);
  }

  if (!productCode) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 text-sm text-slate-300">
        This course has no materials product linked yet, so there is nothing to
        track.{' '}
        <button onClick={gotoSettings} className="text-cyan-300 underline">
          Link one in Settings
        </button>
        .
      </div>
    );
  }

  const alerts = report?.alerts ?? [];
  const sharing = report?.sharing ?? [];

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-300">
        <p>
          <span className="font-semibold text-white">Every download is stamped.</span>{' '}
          The simulator and any HTML lab carry a hidden id unique to that download —
          not to the student, to the download. Two things follow from that: a copy
          that turns up somewhere can be traced back to the account it came from,
          and every copy quietly reports itself the moment it is opened.
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {/* ---- Alerts ---------------------------------------------------- */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40">
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h3 className="flex items-center gap-2 font-semibold text-white">
            {alerts.length ? (
              <ShieldAlert className="h-4 w-4 text-rose-400" />
            ) : (
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
            )}
            Copies that called home from somewhere they should not be
          </h3>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={showReviewed}
                onChange={(e) => setShowReviewed(e.target.checked)}
                className="accent-cyan-500"
              />
              Include reviewed
            </label>
            <button
              onClick={() => void load()}
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:border-cyan-500 hover:text-white"
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Refresh
            </button>
          </div>
        </header>

        {!alerts.length ? (
          <p className="px-4 py-6 text-sm text-slate-400">
            Nothing. Every copy that has been opened was opened on your site, by
            the account it was issued to.{' '}
            {report ? (
              <span className="text-slate-500">
                {report.totals.downloads} download
                {report.totals.downloads === 1 ? '' : 's'} by{' '}
                {report.totals.accounts} account
                {report.totals.accounts === 1 ? '' : 's'} in the last 180 days.
              </span>
            ) : null}
          </p>
        ) : (
          <ul className="divide-y divide-slate-800">
            {alerts.map((a) => {
              const meaning = PING_MEANING[a.status] ?? PING_MEANING.anonymous;
              return (
                <li key={a.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${meaning.tone}`}
                    >
                      {meaning.label}
                    </span>
                    <span className="text-sm text-white">
                      issued to{' '}
                      <span className="font-semibold">{a.issued_to || 'unknown'}</span>
                    </span>
                    <span className="text-xs text-slate-500">{when(a.seen_at)}</span>
                    {a.reviewed_at ? (
                      <span className="text-[11px] text-slate-500">
                        reviewed {when(a.reviewed_at)}
                      </span>
                    ) : (
                      <button
                        onClick={() => void dismiss(a.id)}
                        disabled={busy === a.id}
                        className="ml-auto rounded-lg border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:border-cyan-500 hover:text-white disabled:opacity-40"
                      >
                        {busy === a.id ? 'Saving…' : 'Mark reviewed'}
                      </button>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{meaning.blurb}</p>
                  <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs text-slate-400 sm:grid-cols-2">
                    <div className="sm:col-span-2 break-all">
                      <dt className="inline text-slate-500">Opened at: </dt>
                      <dd className="inline font-mono text-slate-300">
                        {a.page_url || '—'}
                      </dd>
                    </div>
                    <div>
                      <dt className="inline text-slate-500">From IP: </dt>
                      <dd className="inline text-slate-300">{a.ip || '—'}</dd>
                    </div>
                    <div>
                      <dt className="inline text-slate-500">Browser: </dt>
                      <dd className="inline text-slate-300">{browserOf(a.user_agent)}</dd>
                    </div>
                    <div>
                      <dt className="inline text-slate-500">Downloaded: </dt>
                      <dd className="inline text-slate-300">
                        {when(a.issued_at)} from {a.issued_ip || '—'}
                      </dd>
                    </div>
                    {a.session_email ? (
                      <div>
                        <dt className="inline text-slate-500">Signed in as: </dt>
                        <dd className="inline text-slate-300">{a.session_email}</dd>
                      </div>
                    ) : null}
                    {a.timezone ? (
                      <div>
                        <dt className="inline text-slate-500">Time zone: </dt>
                        <dd className="inline text-slate-300">{a.timezone}</dd>
                      </div>
                    ) : null}
                  </dl>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* ---- Account sharing ------------------------------------------- */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40">
        <header className="border-b border-slate-800 px-4 py-3">
          <h3 className="flex items-center gap-2 font-semibold text-white">
            {sharing.length ? (
              <Users className="h-4 w-4 text-amber-400" />
            ) : (
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
            )}
            One login, several people?
          </h3>
          <p className="mt-1 text-xs text-slate-400">
            Every sign-in and every visit is tied to the browser it came from.
            One person is a phone and a laptop; a shared account is many
            devices — or two at the same moment, again and again. Signals
            only: nothing is blocked automatically.
          </p>
        </header>

        {!sharing.length ? (
          <p className="px-4 py-6 text-sm text-slate-400">
            No shared-login signals.{' '}
            <span className="text-slate-500">
              {report?.totals.sharing_tracked ?? 0} account
              {(report?.totals.sharing_tracked ?? 0) === 1 ? '' : 's'} being
              tracked; devices are recorded from each sign-in onward.
            </span>
          </p>
        ) : (
          <ul className="divide-y divide-slate-800">
            {sharing.map((s) => (
              <li key={s.learner_id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
                      s.severity === 'high'
                        ? 'text-rose-300 border-rose-500/40 bg-rose-500/10'
                        : 'text-amber-300 border-amber-500/40 bg-amber-500/10'
                    }`}
                  >
                    {s.severity === 'high' ? 'Likely shared' : 'Worth a look'}
                  </span>
                  <span className="text-sm font-semibold text-white">{s.email}</span>
                  <span className="text-xs text-slate-500">
                    last active {when(s.last_seen_at)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-amber-200/90">
                  {s.reasons.join(' · ')}
                </p>
                <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-400">
                  <span>
                    <span className="text-slate-500">Devices (30d): </span>
                    <span className="text-slate-300">{s.devices_30d}</span>
                  </span>
                  <span>
                    <span className="text-slate-500">IP addresses (30d): </span>
                    <span className="text-slate-300">{s.distinct_ips_30d}</span>
                  </span>
                  <span>
                    <span className="text-slate-500">Simultaneous use: </span>
                    <span className="text-slate-300">
                      {s.overlap_30d} in 30d
                      {s.last_overlap_at ? ` (last ${when(s.last_overlap_at)})` : ''}
                    </span>
                  </span>
                </div>
                {s.devices.length > 0 && (
                  <ul className="mt-2 space-y-0.5">
                    {s.devices.map((d, i) => (
                      <li key={i} className="text-[11px] font-mono text-slate-500">
                        {browserOf(d.user_agent)} · {d.ip || 'ip unknown'} · last{' '}
                        {when(d.last_seen_at)}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ---- Trace ------------------------------------------------------ */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h3 className="font-semibold text-white">Somebody sent you a file — whose is it?</h3>
        <p className="mt-1 text-sm text-slate-400">
          Drop the file in, or paste any part of it. The id survives in four
          separate places, including invisible characters inside the licence
          line, so deleting the obvious one does not help whoever leaked it.
        </p>

        <label
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) void traceFile(f);
          }}
          className="mt-3 flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-slate-700 px-4 py-4 text-sm text-slate-400 hover:border-cyan-500 hover:text-slate-200"
        >
          <input
            type="file"
            accept=".html,.htm,.txt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void traceFile(f);
            }}
          />
          Drop the suspect file here, or click to choose one
        </label>

        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          rows={3}
          placeholder="…or paste the file contents, or just the id, here"
          className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            onClick={() => void runTrace(paste)}
            disabled={tracing || !paste.trim()}
            className="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-cyan-500 disabled:opacity-40"
          >
            {tracing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Trace this copy
          </button>
          {trace ? (
            <button
              onClick={() => {
                setTrace(null);
                setPaste('');
              }}
              className="text-xs text-slate-400 hover:text-white"
            >
              Clear
            </button>
          ) : null}
        </div>

        {trace && trace.verdict === 'traced' && (
          <div className="mt-4 space-y-3">
            {trace.matches.map((m) => (
              <div
                key={m.token}
                className="rounded-lg border border-cyan-500/40 bg-cyan-500/5 p-3"
              >
                <p className="text-sm text-white">
                  Downloaded by{' '}
                  <span className="font-semibold text-cyan-300">{m.email}</span>
                  {m.full_name ? ` (${m.full_name})` : ''} on {when(m.served_at)}.
                </p>
                <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs text-slate-400 sm:grid-cols-2">
                  <div>
                    <dt className="inline text-slate-500">From IP: </dt>
                    <dd className="inline text-slate-300">{m.ip || '—'}</dd>
                  </div>
                  <div>
                    <dt className="inline text-slate-500">Browser: </dt>
                    <dd className="inline text-slate-300">{browserOf(m.user_agent)}</dd>
                  </div>
                  <div>
                    <dt className="inline text-slate-500">File: </dt>
                    <dd className="inline text-slate-300">{m.asset_key}</dd>
                  </div>
                  <div>
                    <dt className="inline text-slate-500">This account has downloaded: </dt>
                    <dd className="inline text-slate-300">
                      {m.downloads_by_this_account ?? '—'} time
                      {m.downloads_by_this_account === 1 ? '' : 's'}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="inline text-slate-500">Copy id: </dt>
                    <dd className="inline font-mono text-slate-300">{m.token}</dd>
                  </div>
                </dl>
                {m.pings?.length ? (
                  <div className="mt-3 border-t border-slate-800 pt-2">
                    <p className="text-xs font-semibold text-slate-300">
                      Every time this exact copy was opened
                    </p>
                    <ul className="mt-1 space-y-1">
                      {m.pings.slice(0, 12).map((p) => (
                        <li key={p.id} className="text-xs text-slate-400">
                          <span
                            className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                              (PING_MEANING[p.status] ?? PING_MEANING.anonymous).tone
                            }`}
                          >
                            {(PING_MEANING[p.status] ?? PING_MEANING.anonymous).label}
                          </span>
                          {when(p.seen_at)} · {p.ip} ·{' '}
                          <span className="break-all font-mono">{p.page_url}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-slate-500">
                    This copy has never reported being opened — it was downloaded
                    and, as far as the platform knows, never run online.
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {trace && trace.verdict === 'no-id-found' && (
          <p className="mt-4 rounded-lg border border-slate-700 bg-slate-950/60 p-3 text-sm text-slate-300">
            No id in that. Either it is not one of your stamped files, or it is an
            older copy from before stamping was switched on
            {report ? '' : ''} — or someone rebuilt the file from scratch.
          </p>
        )}

        {trace && trace.verdict === 'id-not-issued-by-us' && (
          <p className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
            That file carries an id ({trace.unknown_tokens.join(', ')}) that this
            platform never issued. It has been edited, or it came from a copy made
            before stamping was switched on.
          </p>
        )}
      </section>

      {/* ---- Watch list -------------------------------------------------- */}
      {report?.watch?.length ? (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40">
          <header className="border-b border-slate-800 px-4 py-3">
            <h3 className="font-semibold text-white">Worth a look</h3>
            <p className="mt-0.5 text-xs text-slate-400">
              Not proof of anything — accounts whose pattern stands out from the rest.
            </p>
          </header>
          <ul className="divide-y divide-slate-800">
            {report.watch.map((w) => (
              <li key={w.learner_id} className="flex flex-wrap items-baseline gap-x-3 px-4 py-2.5">
                <span className="text-sm font-medium text-white">{w.email}</span>
                <span className="text-xs text-slate-400">{w.reasons.join(' · ')}</span>
                <span className="ml-auto text-xs text-slate-500">
                  last {when(w.last_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* ---- Full log ---------------------------------------------------- */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40">
        <button
          onClick={() => setShowLog((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left"
        >
          <h3 className="font-semibold text-white">
            Download log{' '}
            <span className="text-sm font-normal text-slate-500">
              ({report?.recent.length ?? 0} most recent)
            </span>
          </h3>
          <span className="text-xs text-slate-400">{showLog ? 'Hide' : 'Show'}</span>
        </button>
        {showLog && (
          <div className="overflow-x-auto border-t border-slate-800">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">When</th>
                  <th className="px-4 py-2 font-medium">Account</th>
                  <th className="px-4 py-2 font-medium">File</th>
                  <th className="px-4 py-2 font-medium">IP</th>
                  <th className="px-4 py-2 font-medium">Browser</th>
                  <th className="px-4 py-2 font-medium">Opened</th>
                  <th className="px-4 py-2 font-medium">Copy id</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {(report?.recent ?? []).map((d) => (
                  <tr key={d.token} className="text-slate-300">
                    <td className="whitespace-nowrap px-4 py-1.5">{when(d.served_at)}</td>
                    <td className="px-4 py-1.5">{d.email}</td>
                    <td className="px-4 py-1.5 text-slate-400">{d.asset_key}</td>
                    <td className="px-4 py-1.5 text-slate-400">{d.ip}</td>
                    <td className="whitespace-nowrap px-4 py-1.5 text-slate-400">
                      {browserOf(d.user_agent)}
                    </td>
                    <td className="px-4 py-1.5">
                      {d.ping_count ? (
                        <span
                          className={
                            d.worst_status === 'ok' || !d.worst_status
                              ? 'text-slate-400'
                              : 'text-rose-300'
                          }
                        >
                          {d.ping_count}×{' '}
                          {d.worst_status && d.worst_status !== 'ok'
                            ? (PING_MEANING[d.worst_status] ?? PING_MEANING.anonymous).label
                            : ''}
                        </span>
                      ) : (
                        <span className="text-slate-600">never</span>
                      )}
                    </td>
                    <td className="px-4 py-1.5 font-mono text-slate-500">{d.token}</td>
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
