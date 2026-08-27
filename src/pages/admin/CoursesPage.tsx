/**
 * Courses — one card per cohort (admin course list joined with the per-course
 * stats endpoint) plus the New-course form. Clicking a card opens that
 * course's workspace.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bell,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Download,
  Plus,
  Send,
  Trash2,
  X,
} from 'lucide-react';
import {
  api,
  reportError,
  downloadCsv,
  formatDate,
  formatDay,
  money,
  plainTextToEmailHtml,
  type Course,
  type CourseStats,
  type InterestRow,
  type InterestSummary,
  type NotifyResult,
} from './lib';
import {
  ConfirmButton,
  EmptyState,
  LabeledInput,
  MessageEditor,
  Notice,
  RefreshButton,
  SeatsBar,
  Section,
  StatusBadge,
} from './ui';

type Props = {
  onAuthError: () => void;
  openCourse: (code: string) => void;
};

export default function CoursesPage({ onAuthError, openCourse }: Props) {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [stats, setStats] = useState<CourseStats[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, s] = await Promise.all([
        api<Course[]>('/api/admin/courses'),
        api<{ courses: CourseStats[] }>('/api/admin/stats/courses'),
      ]);
      setCourses(c);
      setStats(s.courses);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const statsByCode = useMemo(() => {
    const m = new Map<string, CourseStats>();
    for (const s of stats ?? []) m.set(s.code, s);
    return m;
  }, [stats]);

  async function createCourse(input: {
    code: string;
    title: string;
    start_date: string;
    total_seats: number;
  }): Promise<boolean> {
    setError(null);
    try {
      const created = await api<Course>('/api/admin/courses', {
        method: 'POST',
        body: JSON.stringify({ ...input, status: 'open' }),
      });
      setCourses((prev) => (prev ? [...prev, created] : [created]));
      setShowCreate(false);
      setFlash(`Course "${input.code}" created. Open it to set price, schedule, and links.`);
      window.setTimeout(() => setFlash(null), 5000);
      return true;
    } catch (e) {
      reportError(e, onAuthError, setError);
      return false;
    }
  }

  return (
    <div className="space-y-6">
      <Section
        icon={<BookOpen className="w-5 h-5 text-cyan-300" />}
        title="Courses"
        sub="Live cohorts — click a course to manage its registrations, buyers, comms, stats, materials, and settings."
        actions={
          <>
            <RefreshButton onClick={() => void load()} loading={loading} />
            <button
              onClick={() => setShowCreate((v) => !v)}
              className="btn-primary flex items-center gap-2 text-sm py-2 px-3"
            >
              <Plus className="w-4 h-4" />
              New course
            </button>
          </>
        }
      >
        {flash && <Notice kind="success">{flash}</Notice>}
        {error && <Notice kind="error">{error}</Notice>}

        {showCreate && (
          <NewCourseForm onCancel={() => setShowCreate(false)} onCreate={createCourse} />
        )}

        {loading && !courses && <div className="p-8 text-slate-300 text-sm">Loading courses…</div>}

        {courses && courses.length === 0 && (
          <div className="card p-8 text-slate-300 text-sm">
            No courses yet — create the first one above.
          </div>
        )}

        {courses && courses.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {courses.map((c) => {
              const s = statsByCode.get(c.code);
              const pending = Math.max(0, c.seats_taken - c.seats_paid);
              return (
                <button
                  key={c.code}
                  onClick={() => openCourse(c.code)}
                  className="card card-hover p-5 text-left w-full hover:border-cyan-500/40 focus:outline-none focus:border-cyan-500/60"
                >
                  <div className="flex items-start justify-between gap-3 mb-1">
                    <div className="min-w-0">
                      <div className="text-xs font-mono text-slate-400 truncate">{c.code}</div>
                      <div className="text-white font-semibold text-lg truncate">{c.title}</div>
                    </div>
                    <StatusBadge status={c.status} />
                  </div>
                  <div className="text-xs text-slate-300 mb-3">
                    Starts {formatDay(c.start_date)}
                    {c.day_dates.length > 0 && (
                      <span className="text-slate-400"> · {c.day_dates.length} days</span>
                    )}
                  </div>
                  <SeatsBar paid={c.seats_paid} taken={c.seats_taken} total={c.total_seats} />
                  <div className="text-xs text-slate-300 mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="text-emerald-300">{c.seats_paid} paid</span>
                    <span className="text-slate-500">·</span>
                    <span className="text-amber-300">{pending} pending</span>
                    <span className="text-slate-500">·</span>
                    <span>{c.seats_remaining} seats remaining</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs mt-3 pt-3 border-t border-slate-800">
                    <span className="text-slate-300">
                      {c.price_cents > 0 ? (
                        <>
                          Seat price{' '}
                          <span className="text-white font-medium">
                            {money(c.price_cents, c.currency)}
                          </span>
                        </>
                      ) : (
                        'Invoice-only (no online payment)'
                      )}
                    </span>
                    {c.recorded_product_code ? (
                      <span className="text-cyan-300">
                        Recorded: {c.recorded_product_code}
                        {s?.recorded && (
                          <> · {money(s.recorded.revenue_cents_total)} · {s.recorded.active_enrollments} learners</>
                        )}
                      </span>
                    ) : (
                      <span className="text-slate-500">No recorded product linked</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </Section>
      <InterestSection onAuthError={onAuthError} />
    </div>
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
    <form onSubmit={submit} className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 mb-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-white">New course</h3>
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
          label="Code (url slug, e.g. gas-turbine-emissions-mapping-2026-09)"
          value={code}
          onChange={setCode}
        />
        <LabeledInput label="Title" value={title} onChange={setTitle} />
        <LabeledInput label="Start date" type="date" value={startDate} onChange={setStartDate} />
        <LabeledInput
          label="Total seats"
          type="number"
          min={1}
          value={totalSeats}
          onChange={setTotalSeats}
        />
      </div>
      <p className="text-[11px] text-slate-400 mt-3">
        Price, day-by-day schedule, and the recorded-product link live in the course's Settings tab
        after creation.
      </p>
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

/**
 * Upcoming-course interest — waitlist signups collected from the public site
 * for courses that do not exist yet. Summary per slug, expandable signup
 * list with spam cleanup, CSV export, and a broadcast composer per slug.
 */
function InterestSection({ onAuthError }: { onAuthError: () => void }) {
  const [summary, setSummary] = useState<InterestSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [rows, setRows] = useState<InterestRow[] | null>(null);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [notifySlug, setNotifySlug] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await api<InterestSummary[]>('/api/admin/interest/summary'));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadRows = useCallback(
    async (slug: string) => {
      setRowsLoading(true);
      try {
        setRows(
          await api<InterestRow[]>(
            `/api/admin/interest?course_slug=${encodeURIComponent(slug)}`,
          ),
        );
      } catch (e) {
        reportError(e, onAuthError, setError);
      } finally {
        setRowsLoading(false);
      }
    },
    [onAuthError],
  );

  async function toggleOpen(slug: string) {
    if (open === slug) {
      setOpen(null);
      setRows(null);
      return;
    }
    setOpen(slug);
    setRows(null);
    await loadRows(slug);
  }

  async function removeRow(id: number) {
    setError(null);
    try {
      await api<{ ok: boolean }>(`/api/admin/interest/${id}`, { method: 'DELETE' });
      setRows((prev) => (prev ? prev.filter((r) => r.id !== id) : prev));
      void load(); // refresh counts
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }

  async function exportCsv(slug: string) {
    setError(null);
    try {
      const data = await api<InterestRow[]>(
        `/api/admin/interest?course_slug=${encodeURIComponent(slug)}`,
      );
      downloadCsv(
        `interest-${slug}.csv`,
        ['Email', 'Name', 'Signed up'],
        data.map((r) => [r.email, r.full_name, r.created_at]),
      );
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }

  return (
    <Section
      icon={<Bell className="w-5 h-5 text-cyan-300" />}
      title="Upcoming-course interest"
      sub="Waitlist signups from the public site for courses that are not built yet — gauge demand, then email each group when its course ships."
      actions={<RefreshButton onClick={() => void load()} loading={loading} />}
    >
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {loading && !summary && (
        <div className="p-8 text-slate-300 text-sm">Loading interest signups…</div>
      )}

      {summary && summary.length === 0 && (
        <EmptyState
          icon={<Bell className="w-5 h-5" />}
          title="No interest signups yet"
          hint="When a visitor leaves their email on an upcoming-course card, that course shows up here with its waitlist."
        />
      )}

      {summary && summary.length > 0 && (
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
          <ul className="divide-y divide-slate-800">
            {summary.map((w) => (
              <li key={w.course_slug}>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
                  <button
                    type="button"
                    onClick={() => void toggleOpen(w.course_slug)}
                    className="flex items-center gap-2 text-left min-w-0 flex-1 group"
                    title={open === w.course_slug ? 'Collapse' : 'Show signups'}
                  >
                    {open === w.course_slug ? (
                      <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
                    )}
                    <span className="font-mono text-sm text-slate-200 truncate group-hover:text-white">
                      {w.course_slug}
                    </span>
                  </button>
                  <span className="text-xs px-2 py-0.5 rounded-full border bg-cyan-500/10 text-cyan-300 border-cyan-500/30 whitespace-nowrap">
                    {w.count} signup{w.count === 1 ? '' : 's'}
                  </span>
                  <span className="text-xs text-slate-400 whitespace-nowrap">
                    {w.latest_at ? `latest ${formatDate(w.latest_at)}` : '—'}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void exportCsv(w.course_slug)}
                      className="btn-secondary flex items-center gap-1 text-xs py-1.5 px-2.5"
                      title="Download this waitlist as CSV"
                    >
                      <Download className="w-3 h-3" />
                      CSV
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setNotifySlug((cur) => (cur === w.course_slug ? null : w.course_slug))
                      }
                      className="btn-primary flex items-center gap-1 text-xs py-1.5 px-2.5"
                    >
                      <Send className="w-3 h-3" />
                      Notify
                    </button>
                  </div>
                </div>

                {open === w.course_slug && (
                  <div className="border-t border-slate-800 bg-slate-950/40">
                    {rowsLoading && (
                      <div className="px-5 py-4 text-sm text-slate-300">Loading…</div>
                    )}
                    {!rowsLoading && rows && rows.length === 0 && (
                      <div className="px-5 py-4 text-sm text-slate-300">
                        No signups left on this waitlist.
                      </div>
                    )}
                    {!rowsLoading && rows && rows.length > 0 && (
                      <ul className="divide-y divide-slate-800/60">
                        {rows.map((r) => (
                          <li
                            key={r.id}
                            className="px-5 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm"
                          >
                            <span className="text-slate-100 min-w-0 flex-1 truncate">
                              {r.email}
                            </span>
                            <span className="text-slate-300 truncate max-w-[220px]">
                              {r.full_name || <span className="text-slate-500">—</span>}
                            </span>
                            <span className="text-xs text-slate-400 whitespace-nowrap">
                              {formatDate(r.created_at)}
                            </span>
                            <ConfirmButton
                              message={`Remove ${r.email} from the ${r.course_slug} waitlist?`}
                              onConfirm={() => void removeRow(r.id)}
                              className="text-slate-400 hover:text-red-300"
                              title="Remove (spam cleanup)"
                            >
                              <Trash2 className="w-4 h-4" />
                            </ConfirmButton>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {notifySlug === w.course_slug && (
                  <WaitlistNotifyForm
                    slug={w.course_slug}
                    count={w.count}
                    onAuthError={onAuthError}
                    onCancel={() => setNotifySlug(null)}
                    onDone={(msg) => {
                      setNotifySlug(null);
                      setFlash(msg);
                      window.setTimeout(() => setFlash(null), 6000);
                    }}
                  />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  );
}

/** Same composer pattern as the course Comms tab, posting to the waitlist notify endpoint. */
function WaitlistNotifyForm({
  slug,
  count,
  onAuthError,
  onDone,
  onCancel,
}: {
  slug: string;
  count: number;
  onAuthError: () => void;
  onDone: (msg: string) => void;
  onCancel: () => void;
}) {
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [rawHtml, setRawHtml] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    if (!subject.trim() || !body.trim()) {
      setError('Subject and body are required.');
      return;
    }
    if (
      !window.confirm(
        `Send "${subject.trim()}" to ${count} waitlist signup${count === 1 ? '' : 's'} for ${slug}?`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const bodyHtml = rawHtml ? body : plainTextToEmailHtml(body);
      const data = await api<NotifyResult>(
        `/api/admin/interest/${encodeURIComponent(slug)}/notify`,
        {
          method: 'POST',
          body: JSON.stringify({ subject: subject.trim(), body_html: bodyHtml }),
        },
      );
      onDone(
        `Waitlist broadcast sent to ${data.recipients} recipient${data.recipients === 1 ? '' : 's'}` +
          (data.failures > 0 ? ` (${data.failures} failed)` : '') +
          '.',
      );
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-t border-slate-800 bg-slate-950/60 p-4 space-y-3">
      <h4 className="text-white font-semibold text-sm flex items-center gap-2">
        <Send className="w-4 h-4 text-cyan-300" /> Email this waitlist
      </h4>
      {error && <Notice kind="error">{error}</Notice>}
      <MessageEditor
        subject={subject}
        onSubject={setSubject}
        body={body}
        onBody={setBody}
        rawHtml={rawHtml}
        onRawHtml={setRawHtml}
      />
      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-slate-300 hover:text-white px-3 py-1.5"
        >
          Cancel
        </button>
        <button
          onClick={() => void send()}
          disabled={busy || !subject.trim() || !body.trim()}
          className="btn-primary flex items-center gap-1 text-sm py-2 px-3 disabled:opacity-50"
        >
          <Send className="w-4 h-4" />
          {busy ? 'Sending…' : `Send to ${count} signup${count === 1 ? '' : 's'}`}
        </button>
      </div>
    </div>
  );
}
