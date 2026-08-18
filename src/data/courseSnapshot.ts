/**
 * Typed access to the build-time course snapshot.
 *
 * course-snapshot.json is written by scripts/fetch-course-data.mjs before the
 * bundle is built, from the same /api/courses/{code} endpoint the pages call at
 * runtime. Pages import their PRERENDER FALLBACK from here instead of typing
 * dates by hand, because the prerendered HTML is what crawlers and no-JS
 * visitors actually read — a hand-typed default goes stale the moment the admin
 * moves a cohort, and then the site advertises a cohort that no longer exists.
 *
 * Live-in-the-browser values still come from the runtime fetch. This module
 * only supplies what to show before that fetch lands.
 */
import snapshotJson from './course-snapshot.json';

export type CourseSnapshot = {
  title: string;
  /** ISO yyyy-mm-dd */
  startDate: string;
  /** ISO yyyy-mm-dd, one per cohort day; length = cohort length */
  dayDates: string[];
  totalSeats: number;
  status: 'open' | 'closed';
  /** "HH:MM" UTC, empty when the admin hasn't set a session time */
  sessionTimeUtc: string;
  sessionDurationMinutes: number;
};

type SnapshotFile = {
  generatedAt?: string;
  source?: string;
  courses?: Record<string, CourseSnapshot>;
};

const snapshot = snapshotJson as SnapshotFile;

/** When the snapshot was last refreshed from the API (ISO timestamp). */
export const SNAPSHOT_GENERATED_AT = snapshot.generatedAt ?? '';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * "2026-08-29" -> "August 29, 2026", parsed by hand so a UTC-midnight Date
 * can't shift the day backwards for viewers west of Greenwich.
 */
export const formatIsoDate = (iso: string): string => {
  const [y, m, d] = String(iso).split('-').map((s) => parseInt(s, 10));
  if (!y || !m || !d || m < 1 || m > 12) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
};

/** The snapshotted course, or null if the build had nothing for this code. */
export const courseSnapshot = (code: string): CourseSnapshot | null =>
  snapshot.courses?.[code] ?? null;

/**
 * Per-day labels for the prerendered schedule, e.g.
 * ["August 29, 2026", ...]. Returns `fallback` only when the snapshot has no
 * entry for this code at all (a brand-new course whose first build couldn't
 * reach the API).
 */
export const snapshotDayLabels = (code: string, fallback: string[] = []): string[] => {
  const dates = courseSnapshot(code)?.dayDates ?? [];
  return dates.length > 0 ? dates.map(formatIsoDate) : fallback;
};

/** Formatted cohort start date for the prerendered HTML. */
export const snapshotStartLabel = (code: string, fallback: string): string => {
  const c = courseSnapshot(code);
  if (!c) return fallback;
  return formatIsoDate(c.dayDates[0] ?? c.startDate);
};
