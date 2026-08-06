/**
 * Overview — the whole platform at a glance. Cross-cutting KPIs, one mini-card
 * per course (click-through to its workspace), the latest outbound emails,
 * and the assistant's most recent activity.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Clock,
  CreditCard,
  Download,
  LayoutDashboard,
  Mail,
  Sparkles,
} from 'lucide-react';
import {
  api,
  reportError,
  formatDate,
  formatDay,
  fmtInt,
  money,
  type AuditRow,
  type CourseStats,
  type EmailLogRow,
  type SoftwareStats,
  type ViewState,
} from './lib';
import { Kpi, Notice, RefreshButton, SeatsBar, Section, StatusBadge } from './ui';

type Props = {
  onAuthError: () => void;
  go: (v: ViewState) => void;
};

export default function OverviewPage({ onAuthError, go }: Props) {
  const [courses, setCourses] = useState<CourseStats[] | null>(null);
  const [software, setSoftware] = useState<SoftwareStats[] | null>(null);
  const [emails, setEmails] = useState<EmailLogRow[] | null>(null);
  const [audit, setAudit] = useState<AuditRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, s, e, a] = await Promise.all([
        api<{ courses: CourseStats[] }>('/api/admin/stats/courses'),
        api<{ software: SoftwareStats[] }>('/api/admin/stats/software'),
        api<{ rows: EmailLogRow[] }>('/api/admin/comms/log?limit=10'),
        api<AuditRow[]>('/api/admin/ai/audit?limit=5'),
      ]);
      setCourses(c.courses);
      setSoftware(s.software);
      setEmails(e.rows);
      setAudit(a);
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const totals = useMemo(() => {
    const t = { pending: 0, paid: 0, revTotal: 0, rev30: 0, dlTotal: 0, dl7: 0 };
    for (const c of courses ?? []) {
      t.pending += c.live.pending;
      t.paid += c.live.paid;
      if (c.recorded) {
        t.revTotal += c.recorded.revenue_cents_total;
        t.rev30 += c.recorded.revenue_cents_30d;
      }
    }
    for (const s of software ?? []) {
      t.dlTotal += s.downloads.total;
      t.dl7 += s.downloads.last7;
    }
    return t;
  }, [courses, software]);

  return (
    <div>
      <Section
        icon={<LayoutDashboard className="w-5 h-5 text-cyan-300" />}
        title="Overview"
        sub="Everything across live cohorts, recorded courses, and software — in one glance."
        actions={<RefreshButton onClick={() => void load()} loading={loading} />}
      >
        {error && <Notice kind="error">{error}</Notice>}

        {/* Cross-platform KPI row */}
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-8">
          <Kpi
            icon={<Clock className="w-4 h-4" />}
            label="Live pending"
            value={courses ? fmtInt(totals.pending) : '—'}
            sub="across all cohorts"
            accent="amber"
          />
          <Kpi
            icon={<CheckCircle2 className="w-4 h-4" />}
            label="Live paid"
            value={courses ? fmtInt(totals.paid) : '—'}
            sub="across all cohorts"
            accent="emerald"
          />
          <Kpi
            icon={<CreditCard className="w-4 h-4" />}
            label="Recorded 30d"
            value={courses ? money(totals.rev30) : '—'}
            sub="revenue, linked products"
            accent="cyan"
          />
          <Kpi
            icon={<CreditCard className="w-4 h-4" />}
            label="Recorded total"
            value={courses ? money(totals.revTotal) : '—'}
            sub="revenue, all time"
            accent="cyan"
          />
          <Kpi
            icon={<Download className="w-4 h-4" />}
            label="Downloads 7d"
            value={software ? fmtInt(totals.dl7) : '—'}
            sub="all software"
            accent="cyan"
          />
          <Kpi
            icon={<Download className="w-4 h-4" />}
            label="Downloads total"
            value={software ? fmtInt(totals.dlTotal) : '—'}
            sub="all software"
            accent="slate"
          />
        </div>
      </Section>

      {/* Per-course mini cards */}
      <div className="mb-8">
        <h3 className="text-sm font-semibold text-white mb-3">Courses</h3>
        {courses === null && loading && (
          <div className="card p-6 text-sm text-slate-300">Loading courses…</div>
        )}
        {courses !== null && courses.length === 0 && (
          <div className="card p-6 text-sm text-slate-300">
            No courses yet — create one from the Courses page.
          </div>
        )}
        {courses !== null && courses.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {courses.map((c) => (
              <button
                key={c.code}
                onClick={() => go({ page: 'courses', course: c.code, tab: 'registrations' })}
                className="card card-hover p-4 text-left w-full hover:border-cyan-500/40 focus:outline-none focus:border-cyan-500/60"
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-[11px] font-mono text-slate-400 truncate">{c.code}</span>
                  <StatusBadge status={c.status} />
                </div>
                <div className="text-white font-semibold truncate">{c.title}</div>
                <div className="text-xs text-slate-300 mt-0.5 mb-3">
                  Starts {formatDay(c.start_date)}
                </div>
                <SeatsBar paid={c.live.paid} taken={c.live.seats_taken} total={c.live.seats_total} />
                <div className="text-xs text-slate-300 mt-2 flex flex-wrap gap-x-2 gap-y-0.5">
                  <span className="text-emerald-300">{c.live.paid} paid</span>
                  <span className="text-slate-500">·</span>
                  <span className="text-amber-300">{c.live.pending} pending</span>
                  <span className="text-slate-500">·</span>
                  <span>{Math.max(0, c.live.seats_total - c.live.seats_taken)} seats left</span>
                </div>
                {c.recorded && (
                  <div className="text-xs text-cyan-300 mt-2">
                    {money(c.recorded.revenue_cents_total)} recorded revenue ·{' '}
                    {c.recorded.active_enrollments} learners
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Latest emails */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Mail className="w-4 h-4 text-cyan-300" /> Latest emails
            </h3>
            <button onClick={() => go({ page: 'comms' })} className="btn-ghost text-xs">
              Full log →
            </button>
          </div>
          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
            {emails === null && loading && (
              <div className="p-5 text-sm text-slate-300">Loading…</div>
            )}
            {emails !== null && emails.length === 0 && (
              <div className="p-5 text-sm text-slate-300">Nothing sent yet.</div>
            )}
            {emails !== null && emails.length > 0 && (
              <table className="w-full text-xs">
                <thead className="bg-slate-950/60 text-slate-300 uppercase tracking-wider">
                  <tr>
                    <th className="px-3 py-2 text-left">When</th>
                    <th className="px-3 py-2 text-left">To</th>
                    <th className="px-3 py-2 text-left">Subject</th>
                    <th className="px-3 py-2 text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {emails.map((r) => (
                    <tr key={r.id}>
                      <td className="px-3 py-2 text-slate-400 whitespace-nowrap">
                        {formatDate(r.ts)}
                      </td>
                      <td className="px-3 py-2 text-slate-300 max-w-[160px] truncate" title={r.recipient}>
                        {r.recipient}
                      </td>
                      <td className="px-3 py-2 text-slate-200 max-w-[220px] truncate" title={r.subject}>
                        {r.subject}
                        {r.scope_code && (
                          <span className="block text-[10px] font-mono text-slate-500 truncate">
                            {r.scope_code} · {r.audience}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className={r.ok ? 'text-emerald-300' : 'text-red-300'}>
                          {r.ok ? 'ok' : 'failed'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Latest AI activity */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-300" /> AI activity
            </h3>
            <button onClick={() => go({ page: 'ai' })} className="btn-ghost text-xs">
              Full activity →
            </button>
          </div>
          <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
            {audit === null && loading && <div className="p-5 text-sm text-slate-300">Loading…</div>}
            {audit !== null && audit.length === 0 && (
              <div className="p-5 text-sm text-slate-300 italic">
                No assistant activity yet — its tool calls and chat turns will land here.
              </div>
            )}
            {audit !== null && audit.length > 0 && (
              <ul className="divide-y divide-slate-800">
                {audit.map((r) => (
                  <li key={r.id} className="px-4 py-3 text-xs">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-wider border ${
                          r.kind === 'tool'
                            ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                            : r.kind === 'cap_hit'
                              ? 'bg-red-500/10 text-red-300 border-red-500/30'
                              : 'bg-slate-700/30 text-slate-300 border-slate-700'
                        }`}
                      >
                        {r.kind === 'tool' ? r.tool_name || 'tool' : r.kind}
                      </span>
                      <span className="text-slate-400">{formatDate(r.created_at)}</span>
                    </div>
                    <div className="text-slate-200 truncate" title={r.summary}>
                      {r.summary}
                    </div>
                    {r.error && (
                      <div className="text-red-300 truncate" title={r.error}>
                        ↳ {r.error}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
