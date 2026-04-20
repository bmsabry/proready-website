import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  CheckCircle2,
  XCircle,
  RefreshCw,
  LogOut,
  Users,
  Clock,
  Ban,
  Mail,
  Briefcase,
  MapPin,
  Calendar,
  BookOpen,
  Send,
  Plus,
  Save,
  Lock,
  Unlock,
  X,
} from 'lucide-react';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

type Registration = {
  id: number;
  course_code: string;
  full_name: string;
  email: string;
  job_title: string;
  company: string;
  years_experience: string;
  location: string;
  status: 'pending' | 'paid' | 'cancelled' | string;
  admin_notes?: string | null;
  created_at: string;
  paid_at?: string | null;
};

type SeatsInfo = { taken: number; capacity: number; cohort: string };

type Course = {
  code: string;
  title: string;
  start_date: string; // yyyy-mm-dd
  total_seats: number;
  status: 'open' | 'closed';
  seats_taken: number;
  seats_remaining: number;
};

const fetchOpts: RequestInit = { credentials: 'include', cache: 'no-store' };

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'bg-amber-500/20 text-amber-200 border-amber-500/40',
    paid: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
    cancelled: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
  };
  const cls = map[status] ?? 'bg-slate-700/30 text-slate-300 border-slate-600/40';
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${cls}`}>
      {status}
    </span>
  );
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [view, setView] = useState<'registrations' | 'courses'>('registrations');
  const [regs, setRegs] = useState<Registration[] | null>(null);
  const [seats, setSeats] = useState<SeatsInfo | null>(null);
  const [adminEmail, setAdminEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadAll = useCallback(async () => {
    if (!API_BASE) {
      setError('VITE_API_BASE is not configured.');
      setLoading(false);
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const [meRes, regsRes, seatsRes] = await Promise.all([
        fetch(`${API_BASE}/api/admin/me`, fetchOpts),
        fetch(`${API_BASE}/api/admin/registrations`, fetchOpts),
        fetch(`${API_BASE}/api/seats`, fetchOpts),
      ]);

      if (meRes.status === 401 || regsRes.status === 401) {
        navigate('/admin/login', { replace: true });
        return;
      }
      if (!meRes.ok) throw new Error(`Session check failed (HTTP ${meRes.status})`);
      if (!regsRes.ok) throw new Error(`Registrations load failed (HTTP ${regsRes.status})`);
      if (!seatsRes.ok) throw new Error(`Seats load failed (HTTP ${seatsRes.status})`);

      const me = (await meRes.json()) as { email: string };
      const list = (await regsRes.json()) as Registration[];
      const s = (await seatsRes.json()) as SeatsInfo;

      setAdminEmail(me.email);
      setRegs(list);
      setSeats(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function handleLogout() {
    if (!API_BASE) return;
    try {
      await fetch(`${API_BASE}/api/admin/logout`, { method: 'POST', credentials: 'include' });
    } catch {
      /* ignore */
    }
    navigate('/admin/login', { replace: true });
  }

  async function action(path: 'mark-paid' | 'cancel', id: number) {
    if (!API_BASE) return;
    if (path === 'cancel' && !window.confirm('Cancel this registration? The seat will be released if it was paid.')) {
      return;
    }
    setBusyId(id);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/${path}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ registration_id: id }),
      });
      if (res.status === 401) {
        navigate('/admin/login', { replace: true });
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({} as any));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const body = (await res.json()) as { taken: number; registration: Registration };
      setRegs((prev) =>
        prev ? prev.map((r) => (r.id === body.registration.id ? body.registration : r)) : prev,
      );
      setSeats((prev) => (prev ? { ...prev, taken: body.taken } : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed.');
    } finally {
      setBusyId(null);
    }
  }

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

  return (
    <section className="min-h-[80vh] bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 py-10 px-4 sm:px-6 lg:px-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Training registrations</h1>
            <p className="text-sm text-slate-400">
              {seats ? `Cohort: ${seats.cohort}` : 'Loading cohort…'}
              {adminEmail && (
                <>
                  {' '}— signed in as <span className="text-slate-200">{adminEmail}</span>
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadAll}
              disabled={loading}
              className="btn-secondary flex items-center gap-2 text-sm py-2 px-3"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            <button
              onClick={handleLogout}
              className="btn-secondary flex items-center gap-2 text-sm py-2 px-3"
            >
              <LogOut className="w-4 h-4" />
              Sign out
            </button>
          </div>
        </div>

        {/* View tabs */}
        <div className="flex items-center gap-2 mb-6 border-b border-slate-800">
          <button
            onClick={() => setView('registrations')}
            className={`flex items-center gap-2 text-sm px-4 py-2 border-b-2 -mb-px transition-colors ${
              view === 'registrations'
                ? 'border-cyan-400 text-cyan-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Users className="w-4 h-4" />
            Registrations
          </button>
          <button
            onClick={() => setView('courses')}
            className={`flex items-center gap-2 text-sm px-4 py-2 border-b-2 -mb-px transition-colors ${
              view === 'courses'
                ? 'border-cyan-400 text-cyan-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            Courses
          </button>
        </div>

        {view === 'courses' ? (
          <CoursesTab
            onAuthError={() => navigate('/admin/login', { replace: true })}
          />
        ) : (
          <RegistrationsTab
            regs={regs}
            seats={seats}
            loading={loading}
            error={error}
            busyId={busyId}
            action={action}
            counts={counts}
          />
        )}
      </div>
    </section>
  );
}

type RegistrationsTabProps = {
  regs: Registration[] | null;
  seats: SeatsInfo | null;
  loading: boolean;
  error: string | null;
  busyId: number | null;
  action: (path: 'mark-paid' | 'cancel', id: number) => void;
  counts: { pending: number; paid: number; cancelled: number; total: number };
};

function RegistrationsTab({
  regs,
  seats,
  loading,
  error,
  busyId,
  action,
  counts,
}: RegistrationsTabProps) {
  return (
    <>
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
          <Kpi
            icon={<Users className="w-4 h-4" />}
            label="Paid seats"
            value={seats ? `${seats.taken} / ${seats.capacity}` : '—'}
            accent="emerald"
          />
          <Kpi
            icon={<Clock className="w-4 h-4" />}
            label="Pending"
            value={counts.pending}
            accent="amber"
          />
          <Kpi
            icon={<CheckCircle2 className="w-4 h-4" />}
            label="Paid"
            value={counts.paid}
            accent="emerald"
          />
          <Kpi
            icon={<Ban className="w-4 h-4" />}
            label="Cancelled"
            value={counts.cancelled}
            accent="slate"
          />
        </div>

        {error && (
          <div className="mb-4 text-sm text-red-300 bg-red-950/40 border border-red-900/60 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {/* Table */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden"
        >
          {loading && !regs && (
            <div className="p-8 text-slate-400 text-sm">Loading registrations…</div>
          )}
          {regs && regs.length === 0 && (
            <div className="p-8 text-slate-400 text-sm">No registrations yet.</div>
          )}
          {regs && regs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-950/60 text-slate-400 text-xs uppercase tracking-wide">
                  <tr>
                    <th className="text-left px-4 py-3">Applicant</th>
                    <th className="text-left px-4 py-3">Company / Role</th>
                    <th className="text-left px-4 py-3">Location</th>
                    <th className="text-left px-4 py-3">Status</th>
                    <th className="text-left px-4 py-3 whitespace-nowrap">Registered</th>
                    <th className="text-right px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {regs.map((r) => (
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
                        <div className="text-xs text-slate-400 flex items-center gap-1 mt-0.5">
                          <Briefcase className="w-3 h-3" />
                          {r.job_title}
                          <span className="text-slate-600">·</span>
                          {r.years_experience} yrs
                        </div>
                      </td>
                      <td className="px-4 py-3 align-top text-slate-300 whitespace-nowrap">
                        <div className="flex items-center gap-1">
                          <MapPin className="w-3 h-3 text-slate-500" />
                          {r.location}
                        </div>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <StatusBadge status={r.status} />
                        {r.paid_at && (
                          <div className="text-[11px] text-slate-500 mt-1">
                            paid {formatDate(r.paid_at)}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 align-top text-slate-400 text-xs whitespace-nowrap">
                        {formatDate(r.created_at)}
                      </td>
                      <td className="px-4 py-3 align-top">
                        <div className="flex items-center justify-end gap-2">
                          {r.status !== 'paid' && (
                            <button
                              onClick={() => action('mark-paid', r.id)}
                              disabled={busyId === r.id}
                              className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-emerald-600/90 hover:bg-emerald-500 text-white disabled:opacity-50"
                            >
                              <CheckCircle2 className="w-3 h-3" />
                              Mark paid
                            </button>
                          )}
                          {r.status !== 'cancelled' && (
                            <button
                              onClick={() => action('cancel', r.id)}
                              disabled={busyId === r.id}
                              className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 disabled:opacity-50"
                            >
                              <XCircle className="w-3 h-3" />
                              Cancel
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </motion.div>
    </>
  );
}

function Kpi({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  accent: 'emerald' | 'amber' | 'slate';
}) {
  const tone = {
    emerald: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
    amber: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
    slate: 'text-slate-300 bg-slate-500/10 border-slate-500/30',
  }[accent];
  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-2 text-xs text-slate-400 uppercase tracking-wide">
        <span className={`inline-flex items-center justify-center w-6 h-6 rounded-md border ${tone}`}>
          {icon}
        </span>
        {label}
      </div>
      <div className="text-2xl font-semibold text-white mt-2">{value}</div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Courses tab — list, create, edit, notify
// -----------------------------------------------------------------------------

type CoursePatch = {
  title?: string;
  start_date?: string;
  total_seats?: number;
  status?: 'open' | 'closed';
};

type NotifyTarget = { code: string; title: string } | null;

function CoursesTab({ onAuthError }: { onAuthError: () => void }) {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, CoursePatch>>({});
  const [notifyTarget, setNotifyTarget] = useState<NotifyTarget>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    if (!API_BASE) {
      setError('VITE_API_BASE is not configured.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/courses`, fetchOpts);
      if (res.status === 401) {
        onAuthError();
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setCourses((await res.json()) as Course[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Load failed.');
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    load();
  }, [load]);

  function patchEdit(code: string, patch: CoursePatch) {
    setEdits((prev) => ({ ...prev, [code]: { ...prev[code], ...patch } }));
  }

  function clearEdit(code: string) {
    setEdits((prev) => {
      const { [code]: _drop, ...rest } = prev;
      return rest;
    });
  }

  async function save(code: string) {
    const patch = edits[code];
    if (!patch || Object.keys(patch).length === 0) return;
    setSaving(code);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/courses/${code}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (res.status === 401) {
        onAuthError();
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
      setCourses((prev) =>
        prev ? prev.map((c) => (c.code === code ? (body as Course) : c)) : prev,
      );
      clearEdit(code);
      setFlash(
        patch.start_date
          ? `Saved ${code}. Registrants notified of the new start date.`
          : `Saved ${code}.`,
      );
      window.setTimeout(() => setFlash(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed.');
    } finally {
      setSaving(null);
    }
  }

  async function toggleStatus(code: string, current: 'open' | 'closed') {
    const next: 'open' | 'closed' = current === 'open' ? 'closed' : 'open';
    setSaving(code);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/courses/${code}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: next }),
      });
      if (res.status === 401) {
        onAuthError();
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
      setCourses((prev) =>
        prev ? prev.map((c) => (c.code === code ? (body as Course) : c)) : prev,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update failed.');
    } finally {
      setSaving(null);
    }
  }

  async function createCourse(input: {
    code: string;
    title: string;
    start_date: string;
    total_seats: number;
  }) {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/courses`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...input, status: 'open' }),
      });
      if (res.status === 401) {
        onAuthError();
        return false;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
      setCourses((prev) => (prev ? [...prev, body as Course] : [body as Course]));
      setShowCreate(false);
      setFlash(`Course "${input.code}" created.`);
      window.setTimeout(() => setFlash(null), 4000);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed.');
      return false;
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-cyan-300" />
          Courses
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="btn-secondary flex items-center gap-2 text-sm py-2 px-3"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="btn-primary flex items-center gap-2 text-sm py-2 px-3"
          >
            <Plus className="w-4 h-4" />
            New course
          </button>
        </div>
      </div>

      {flash && (
        <div className="mb-4 text-sm text-emerald-200 bg-emerald-950/40 border border-emerald-900/60 rounded-lg px-3 py-2">
          {flash}
        </div>
      )}
      {error && (
        <div className="mb-4 text-sm text-red-300 bg-red-950/40 border border-red-900/60 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {showCreate && (
        <NewCourseForm onCancel={() => setShowCreate(false)} onCreate={createCourse} />
      )}

      {loading && !courses && (
        <div className="p-8 text-slate-400 text-sm">Loading courses…</div>
      )}

      {courses && courses.length === 0 && (
        <div className="p-8 text-slate-400 text-sm">No courses yet.</div>
      )}

      {courses && courses.length > 0 && (
        <div className="space-y-3">
          {courses.map((c) => {
            const edit = edits[c.code];
            const dirty = !!edit && Object.keys(edit).length > 0;
            const values = {
              title: edit?.title ?? c.title,
              start_date: edit?.start_date ?? c.start_date,
              total_seats: edit?.total_seats ?? c.total_seats,
            };
            return (
              <div
                key={c.code}
                className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5"
              >
                <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                  <div>
                    <div className="text-xs font-mono text-slate-500">{c.code}</div>
                    <div className="text-white font-semibold text-lg">{c.title}</div>
                    <div className="text-xs text-slate-400 mt-1">
                      {c.seats_taken} paid · {c.seats_remaining} seats remaining
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleStatus(c.code, c.status)}
                      disabled={saving === c.code}
                      className={`inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md border disabled:opacity-50 ${
                        c.status === 'open'
                          ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-200'
                          : 'bg-slate-800/60 border-slate-700 text-slate-300'
                      }`}
                    >
                      {c.status === 'open' ? (
                        <>
                          <Unlock className="w-3 h-3" />
                          Open
                        </>
                      ) : (
                        <>
                          <Lock className="w-3 h-3" />
                          Closed
                        </>
                      )}
                    </button>
                    <button
                      onClick={() => setNotifyTarget({ code: c.code, title: c.title })}
                      className="btn-secondary flex items-center gap-1 text-xs py-1.5 px-3"
                    >
                      <Send className="w-3 h-3" />
                      Notify
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <LabeledInput
                    label="Title"
                    value={values.title}
                    onChange={(v) => patchEdit(c.code, { title: v })}
                  />
                  <LabeledInput
                    label="Start date"
                    type="date"
                    value={values.start_date}
                    onChange={(v) => patchEdit(c.code, { start_date: v })}
                    icon={<Calendar className="w-3 h-3 text-slate-500" />}
                  />
                  <LabeledInput
                    label="Total seats"
                    type="number"
                    min={1}
                    value={String(values.total_seats)}
                    onChange={(v) => {
                      const n = parseInt(v, 10);
                      if (!Number.isNaN(n)) patchEdit(c.code, { total_seats: n });
                    }}
                  />
                </div>

                {dirty && (
                  <div className="mt-4 flex items-center justify-between gap-3 text-xs text-amber-200 bg-amber-950/40 border border-amber-900/60 rounded-lg px-3 py-2">
                    <span>
                      {edit?.start_date
                        ? 'Saving will email all registrants about the new start date.'
                        : 'Unsaved changes.'}
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => clearEdit(c.code)}
                        className="text-slate-300 hover:text-white"
                      >
                        Discard
                      </button>
                      <button
                        onClick={() => save(c.code)}
                        disabled={saving === c.code}
                        className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50"
                      >
                        <Save className="w-3 h-3" />
                        {saving === c.code ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {notifyTarget && (
        <NotifyModal
          target={notifyTarget}
          onClose={() => setNotifyTarget(null)}
          onAuthError={onAuthError}
          onFlash={(msg) => {
            setFlash(msg);
            window.setTimeout(() => setFlash(null), 5000);
          }}
        />
      )}
    </div>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  type = 'text',
  min,
  icon,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  min?: number;
  icon?: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider text-slate-400 flex items-center gap-1 mb-1">
        {icon}
        {label}
      </span>
      <input
        type={type}
        min={min}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
      />
    </label>
  );
}

function NewCourseForm({
  onCancel,
  onCreate,
}: {
  onCancel: () => void;
  onCreate: (input: {
    code: string;
    title: string;
    start_date: string;
    total_seats: number;
  }) => Promise<boolean>;
}) {
  const [code, setCode] = useState('');
  const [title, setTitle] = useState('');
  const [startDate, setStartDate] = useState('');
  const [totalSeats, setTotalSeats] = useState('15');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const ok = await onCreate({
      code: code.trim(),
      title: title.trim(),
      start_date: startDate,
      total_seats: parseInt(totalSeats, 10) || 1,
    });
    setBusy(false);
    if (ok) {
      setCode('');
      setTitle('');
      setStartDate('');
      setTotalSeats('15');
    }
  }

  return (
    <form
      onSubmit={submit}
      className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 mb-5"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-white">New course</h3>
        <button
          type="button"
          onClick={onCancel}
          className="text-slate-400 hover:text-white"
          aria-label="Close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <LabeledInput
          label="Code (url slug, e.g. gas-turbine-emissions-mapping-2026-09)"
          value={code}
          onChange={setCode}
        />
        <LabeledInput label="Title" value={title} onChange={setTitle} />
        <LabeledInput
          label="Start date"
          type="date"
          value={startDate}
          onChange={setStartDate}
        />
        <LabeledInput
          label="Total seats"
          type="number"
          min={1}
          value={totalSeats}
          onChange={setTotalSeats}
        />
      </div>
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
          disabled={busy || !code || !title || !startDate}
          className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
        >
          <Plus className="w-4 h-4" />
          {busy ? 'Creating…' : 'Create'}
        </button>
      </div>
    </form>
  );
}

function NotifyModal({
  target,
  onClose,
  onAuthError,
  onFlash,
}: {
  target: { code: string; title: string };
  onClose: () => void;
  onAuthError: () => void;
  onFlash: (msg: string) => void;
}) {
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [audience, setAudience] = useState<'all' | 'paid' | 'pending'>('all');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function send() {
    if (!subject.trim() || !body.trim()) {
      setErr('Subject and body are required.');
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/courses/${target.code}/notify`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject: subject.trim(),
          body_html: body,
          audience,
        }),
      });
      if (res.status === 401) {
        onAuthError();
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
      onFlash(
        `Broadcast sent to ${data.recipients} registrant${data.recipients === 1 ? '' : 's'}` +
          (data.failures > 0 ? ` (${data.failures} failed)` : '') +
          '.',
      );
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Send failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <div>
            <div className="text-xs text-slate-500 font-mono">{target.code}</div>
            <h3 className="text-white font-semibold">Broadcast to {target.title} registrants</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">
              Audience
            </label>
            <div className="flex flex-wrap gap-2">
              {(['all', 'paid', 'pending'] as const).map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAudience(a)}
                  className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                    audience === a
                      ? 'bg-cyan-500/20 border-cyan-500/60 text-cyan-200'
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {a === 'all' ? 'All (paid + pending)' : a === 'paid' ? 'Paid only' : 'Pending only'}
                </button>
              ))}
            </div>
          </div>

          <LabeledInput label="Subject" value={subject} onChange={setSubject} />

          <label className="block">
            <span className="text-xs uppercase tracking-wider text-slate-400 mb-1 block">
              Message (HTML supported)
            </span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={10}
              placeholder="<p>Hi everyone,</p><p>A quick update…</p>"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
            />
            <span className="text-[11px] text-slate-500 mt-1 block">
              Use simple HTML like &lt;p&gt;, &lt;strong&gt;, &lt;a href&gt;. Plain text also works.
            </span>
          </label>

          {err && (
            <div className="text-sm text-red-300 bg-red-950/40 border border-red-900/60 rounded-lg px-3 py-2">
              {err}
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-slate-800 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="text-sm text-slate-300 hover:text-white px-3 py-1.5"
          >
            Cancel
          </button>
          <button
            onClick={send}
            disabled={busy}
            className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
            {busy ? 'Sending…' : 'Send broadcast'}
          </button>
        </div>
      </div>
    </div>
  );
}
