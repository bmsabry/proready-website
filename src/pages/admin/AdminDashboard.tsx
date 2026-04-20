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
      </div>
    </section>
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
