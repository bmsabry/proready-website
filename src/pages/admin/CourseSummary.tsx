/**
 * A course at a glance, in two lines, the same everywhere it appears
 * (Overview, Courses, a course's Stats tab):
 *
 *   Now      — the current offering: the next (or running) cohort's dates,
 *              and its own seats — paid, pending, left. Nobody from an
 *              earlier cohort is counted here.
 *   All time — what the course has done: cohorts delivered, people trained,
 *              fees recorded, and the recorded course's learners and sales.
 */
import { Fragment } from 'react';
import { money, type CourseStats } from './lib';

const DAY = 86_400_000;

function parseDay(iso: string): Date {
  return new Date(`${iso.slice(0, 10)}T00:00:00`);
}

/** "Nov 14 – 22, 2026", "Oct 30 – Nov 2, 2026", "Dec 30, 2026 – Jan 3, 2027". */
export function dateRange(startIso: string | null, endIso: string | null): string {
  if (!startIso) return '';
  const a = parseDay(startIso);
  const b = parseDay(endIso || startIso);
  const md = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  if (a.getTime() === b.getTime()) return `${md(a)}, ${a.getFullYear()}`;
  if (a.getFullYear() !== b.getFullYear())
    return `${md(a)}, ${a.getFullYear()} – ${md(b)}, ${b.getFullYear()}`;
  if (a.getMonth() === b.getMonth()) return `${md(a)} – ${b.getDate()}, ${b.getFullYear()}`;
  return `${md(a)} – ${md(b)}, ${b.getFullYear()}`;
}

/** Where the current cohort stands in time, in words. */
export function cohortTiming(s: CourseStats): { text: string; tone: 'ok' | 'running' | 'stale' } {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = parseDay(s.cohort.start);
  const end = parseDay(s.cohort.end);
  const range = dateRange(s.cohort.start, s.cohort.end);
  if (today > end) {
    return { text: `Dates ${range} have passed — set the next cohort's dates`, tone: 'stale' };
  }
  if (today >= start) return { text: `Running now · ${range}`, tone: 'running' };
  const days = Math.round((start.getTime() - today.getTime()) / DAY);
  return {
    text: `Next cohort ${range} · starts ${days === 1 ? 'tomorrow' : `in ${days} days`}`,
    tone: 'ok',
  };
}

function Label({ children }: { children: string }) {
  return (
    <span className="inline-block text-[10px] font-semibold uppercase tracking-wider text-slate-400 mr-2">
      {children}
    </span>
  );
}

/** Line 1 — the current offering. */
export function CurrentLine({ s }: { s: CourseStats }) {
  const t = cohortTiming(s);
  const left = Math.max(0, s.live.seats_total - s.live.seats_taken);
  return (
    <div className="text-xs">
      <div
        className={`mb-1 ${
          t.tone === 'stale' ? 'text-amber-300' : t.tone === 'running' ? 'text-cyan-300' : 'text-slate-300'
        }`}
      >
        <Label>Now</Label>
        {s.status === 'closed' ? `Registration closed · ${t.text}` : t.text}
      </div>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-slate-300">
        <span className="text-emerald-300">{s.live.paid} paid</span>
        <span className="text-slate-500">·</span>
        <span className="text-amber-300">{s.live.pending} pending</span>
        <span className="text-slate-500">·</span>
        <span>
          {left} of {s.live.seats_total} seats left
        </span>
        {s.live.cancelled > 0 && (
          <>
            <span className="text-slate-500">·</span>
            <span className="text-slate-400">{s.live.cancelled} cancelled</span>
          </>
        )}
      </div>
    </div>
  );
}

/** Line 2 — the course's history, all time. */
export function HistoryLine({ s }: { s: CourseStats }) {
  const h = s.history;
  const parts: string[] = [];
  if (h.cohorts_run === 0) {
    parts.push('No cohort delivered yet');
  } else {
    const last = h.cohorts[0];
    parts.push(
      `${h.cohorts_run} cohort${h.cohorts_run === 1 ? '' : 's'} delivered` +
        (last?.start ? ` (latest ${dateRange(last.start, last.end)})` : ''),
    );
    parts.push(`${h.trained} trained`);
  }
  if (h.fees_cents > 0) parts.push(`${money(h.fees_cents, s.cohort.currency)} collected online`);
  if (s.recorded) {
    parts.push(
      `${s.recorded.active_enrollments} with recorded-course access`,
      `${money(s.recorded.revenue_cents_total)} recorded sales`,
    );
  }
  return (
    <div className="text-xs text-slate-400 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <Label>All time</Label>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i > 0 && <span className="text-slate-600">·</span>}
          <span>{p}</span>
        </Fragment>
      ))}
    </div>
  );
}
