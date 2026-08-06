/**
 * Courses — one card per cohort (admin course list joined with the per-course
 * stats endpoint) plus the New-course form. Clicking a card opens that
 * course's workspace.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, Plus, X } from 'lucide-react';
import {
  api,
  reportError,
  formatDay,
  money,
  type Course,
  type CourseStats,
} from './lib';
import { LabeledInput, Notice, RefreshButton, SeatsBar, Section, StatusBadge } from './ui';

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
