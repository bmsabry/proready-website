/**
 * Build-time course snapshot.
 *
 * WHY THIS EXISTS
 * ---------------
 * Every public course page is prerendered to static HTML at build time and
 * only swaps to live API data after hydration. So whatever the component uses
 * as its "loading" default is ALSO what Google, LinkedIn previews, and any
 * no-JS visitor read. Twice now those defaults were hand-typed constants that
 * went stale after the admin moved a cohort in the dashboard, and the site
 * advertised a cohort that no longer existed.
 *
 * This script removes the class of bug rather than fixing another instance:
 * the defaults are no longer typed by a human, they are fetched from the same
 * /api/courses/{code} endpoint the page uses at runtime and written to
 * src/data/course-snapshot.json, which the pages import.
 *
 * RULES THIS SCRIPT FOLLOWS
 * -------------------------
 * 1. It NEVER fails the build. Render's free tier sleeps; a cold start or a
 *    blip must not take the website deploy down with it. On any failure the
 *    committed snapshot (last known good) is kept and the log says so loudly.
 * 2. It refuses to overwrite a good snapshot with a bad payload. A course with
 *    no parseable day_dates is treated as a failed fetch, not as new truth.
 * 3. It only writes when the course facts actually changed, so `generatedAt`
 *    doesn't churn the diff on every local build.
 * 4. It snapshots only SLOW-MOVING facts (dates, seat capacity, session time).
 *    Seats taken and price are deliberately excluded — a stale "3 seats left"
 *    baked into static HTML is worse than the generic label the page shows
 *    until the live fetch lands.
 */
import { readFileSync, writeFileSync } from 'node:fs';

// Course codes whose pages are prerendered. Add a code here when a new live
// cohort gets its own public page.
const COURSE_CODES = [
  'gas-turbine-emissions-mapping-2026-05',
  'micro-gas-turbine-design-2026-10',
];

const SNAPSHOT_PATH = new URL('../src/data/course-snapshot.json', import.meta.url);

// Same variable the client bundle reads, so the build and the browser always
// agree on which backend is authoritative.
const API_BASE = (process.env.VITE_API_BASE ?? '').trim().replace(/\/+$/, '');

const ATTEMPTS = 3;
const TIMEOUT_MS = 45_000; // Render cold starts are slow; give them room.

const log = (msg) => console.log(`  [course-snapshot] ${msg}`);
const warn = (msg) => console.warn(`  [course-snapshot] ${msg}`);

const isIsoDate = (s) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s);

/** Fetch one course, retrying a cold backend. Returns null if unusable. */
async function fetchCourse(code) {
  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    try {
      const res = await fetch(`${API_BASE}/api/courses/${code}`, {
        signal: AbortSignal.timeout(TIMEOUT_MS),
        headers: { accept: 'application/json' },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Validate before trusting. A malformed payload must not be allowed to
      // erase a good snapshot.
      const dayDates = Array.isArray(data.day_dates) ? data.day_dates.filter(isIsoDate) : [];
      if (dayDates.length === 0) throw new Error('payload has no usable day_dates');
      if (!isIsoDate(data.start_date)) throw new Error('payload has no usable start_date');

      return {
        title: typeof data.title === 'string' ? data.title : '',
        startDate: data.start_date,
        dayDates,
        totalSeats: Number.isFinite(data.total_seats) ? data.total_seats : 0,
        status: data.status === 'closed' ? 'closed' : 'open',
        sessionTimeUtc: typeof data.session_time_utc === 'string' ? data.session_time_utc : '',
        sessionDurationMinutes: Number.isFinite(data.session_duration_minutes)
          ? data.session_duration_minutes
          : 0,
      };
    } catch (err) {
      const last = attempt === ATTEMPTS;
      warn(`${code}: attempt ${attempt}/${ATTEMPTS} failed (${err.message})${last ? '' : ' — retrying'}`);
      if (!last) await new Promise((r) => setTimeout(r, attempt * 3000));
    }
  }
  return null;
}

function readSnapshot() {
  try {
    return JSON.parse(readFileSync(SNAPSHOT_PATH, 'utf8'));
  } catch {
    return { generatedAt: '', source: '', courses: {} };
  }
}

const existing = readSnapshot();

if (!API_BASE) {
  warn('VITE_API_BASE is not set — keeping the committed snapshot.');
  warn('On Cloudflare Pages this variable IS set, so production builds fetch live data.');
  process.exit(0);
}

log(`fetching ${COURSE_CODES.length} course(s) from ${API_BASE}`);

const courses = { ...(existing.courses ?? {}) };
let live = 0;
let kept = 0;

for (const code of COURSE_CODES) {
  const fresh = await fetchCourse(code);
  if (fresh) {
    courses[code] = fresh;
    live++;
    log(`${code}: ${fresh.dayDates.length} day(s), starts ${fresh.startDate}, ${fresh.status}`);
  } else if (courses[code]) {
    kept++;
    warn(`${code}: using the committed snapshot (starts ${courses[code].startDate}) — it may be stale.`);
  } else {
    kept++;
    warn(`${code}: no live data AND no committed snapshot. The page falls back to its in-file default.`);
  }
}

// Write only when a course fact actually changed, so generatedAt doesn't churn
// the git diff on every build.
const changed = JSON.stringify(courses) !== JSON.stringify(existing.courses ?? {});
if (changed) {
  const out = {
    _comment:
      'GENERATED by scripts/fetch-course-data.mjs — do not hand-edit. Change course dates in the admin dashboard; the next build picks them up.',
    generatedAt: new Date().toISOString(),
    source: API_BASE,
    courses,
  };
  writeFileSync(SNAPSHOT_PATH, `${JSON.stringify(out, null, 2)}\n`);
  log('snapshot updated (course facts changed since the last build).');
} else {
  log('snapshot unchanged.');
}

log(`done — ${live} live, ${kept} fallback.`);
