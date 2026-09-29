/**
 * Live-session times for every place a course page lists, date by date.
 *
 * Bassam sets the start on his own clock (New York) in the admin. Every other
 * place is derived from that for each session DATE, using that date's
 * daylight-saving rules for both ends: New York and Vancouver change clocks
 * together in March and November, Europe changes on different weekends, and
 * Saudi Arabia and Algeria never change. A single fixed offset — or a single
 * UTC time — is wrong for part of the year, so nothing here stores one.
 *
 * The backend does the same arithmetic in Python (app/local_times.py,
 * session_start_utc) for the reminder emails; both read the same IANA rules.
 */

export const INSTRUCTOR_ZONE = 'America/New_York';

export type SessionClock = {
  /** "HH:MM" on the instructor's clock; '' when not set. The source of truth. */
  local: string;
  /** IANA zone of that clock. */
  zone: string;
  /** Legacy "HH:MM" UTC — used only when `local` is empty (older API). */
  utc: string;
  durationMinutes: number;
};

export type Place = { place: string; region: string; zone: string };

/** The places the public course pages show, in display order. */
export const COURSE_PLACES: Place[] = [
  { place: 'Vancouver', region: 'Pacific Time', zone: 'America/Vancouver' },
  { place: 'New York', region: 'Eastern Time', zone: 'America/New_York' },
  { place: 'Algeria', region: '', zone: 'Africa/Algiers' },
  { place: 'Saudi Arabia', region: '', zone: 'Asia/Riyadh' },
];

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const MINUTE = 60_000;

export const EMPTY_CLOCK: SessionClock = { local: '', zone: INSTRUCTOR_ZONE, utc: '', durationMinutes: 0 };

/** Read the session fields of an /api/courses payload. */
export const clockFromApi = (data: {
  session_time_local?: unknown;
  session_timezone?: unknown;
  session_time_utc?: unknown;
  session_duration_minutes?: unknown;
}): SessionClock => ({
  local: typeof data.session_time_local === 'string' ? data.session_time_local : '',
  zone:
    typeof data.session_timezone === 'string' && data.session_timezone
      ? data.session_timezone
      : INSTRUCTOR_ZONE,
  utc: typeof data.session_time_utc === 'string' ? data.session_time_utc : '',
  durationMinutes:
    typeof data.session_duration_minutes === 'number' && Number.isFinite(data.session_duration_minutes)
      ? data.session_duration_minutes
      : 0,
});

export const hasSessionTime = (c: SessionClock): boolean => HHMM.test(c.local) || HHMM.test(c.utc);

const partsFormatters = new Map<string, Intl.DateTimeFormat>();
const zoneParts = (zone: string, ms: number): Record<string, number> => {
  let f = partsFormatters.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    partsFormatters.set(zone, f);
  }
  const out: Record<string, number> = {};
  for (const p of f.formatToParts(new Date(ms))) {
    if (p.type !== 'literal') out[p.type] = parseInt(p.value, 10);
  }
  return out;
};

/** Minutes `zone` is ahead of UTC at instant `ms` (e.g. -300 for EST). */
export const offsetMinutes = (zone: string, ms: number): number => {
  const p = zoneParts(zone, ms);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second);
  return Math.round((asUtc - Math.floor(ms / 1000) * 1000) / MINUTE);
};

/** `hhmm` on `dayIso`, read on a clock in `zone`, as a UTC instant (ms). */
export const wallClockToUtcMs = (dayIso: string, hhmm: string, zone: string): number => {
  const [y, m, d] = dayIso.split('-').map((n) => parseInt(n, 10));
  const [hh, mm] = hhmm.split(':').map((n) => parseInt(n, 10));
  const asIfUtc = Date.UTC(y, m - 1, d, hh, mm);
  // Two passes: the offset at the first guess can be the other side of a
  // clock change from the real instant.
  const first = asIfUtc - offsetMinutes(zone, asIfUtc) * MINUTE;
  const second = asIfUtc - offsetMinutes(zone, first) * MINUTE;
  // A time that does not exist (skipped when clocks go forward) is read with
  // the offset from before the change — the same rule Python's zoneinfo uses,
  // so the page and the reminder emails can never disagree.
  return clockTime(second, zone, '24h') === hhmm ? second : first;
};

/** One UTC start (ms) per session day, in day order; [] when no time is set. */
export const sessionStartsUtcMs = (clock: SessionClock, dayIsos: string[]): number[] => {
  if (HHMM.test(clock.local)) {
    return dayIsos.map((d) => wallClockToUtcMs(d, clock.local, clock.zone || INSTRUCTOR_ZONE));
  }
  if (HHMM.test(clock.utc)) return dayIsos.map((d) => wallClockToUtcMs(d, clock.utc, 'UTC'));
  return [];
};

/** "9:00 AM" (12h) or "09:00" (24h) on a clock in `zone`. */
export const clockTime = (ms: number, zone: string, style: '12h' | '24h' = '12h'): string => {
  const p = zoneParts(zone, ms);
  const h = p.hour % 24;
  const mm = String(p.minute).padStart(2, '0');
  if (style === '24h') return `${String(h).padStart(2, '0')}:${mm}`;
  return `${((h + 11) % 12) + 1}:${mm} ${h < 12 ? 'AM' : 'PM'}`;
};

/** "UTC+3", "UTC−8", "UTC+5:30" — the offset in force at that instant. */
export const utcOffsetLabel = (ms: number, zone: string): string => {
  const off = offsetMinutes(zone, ms);
  const sign = off < 0 ? '−' : '+';
  const abs = Math.abs(off);
  const mins = abs % 60;
  return `UTC${sign}${Math.floor(abs / 60)}${mins ? `:${String(mins).padStart(2, '0')}` : ''}`;
};

/** Calendar date ("YYYY-MM-DD") at instant `ms` on a clock in `zone`. */
export const localDateIso = (ms: number, zone: string): string => {
  const p = zoneParts(zone, ms);
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`;
};

export type TimesPeriod = {
  /** First session date (instructor's calendar) these times apply from. */
  fromDayIso: string;
  start: string;
  end: string;
  /** 'next day' / 'previous day' when the local date differs from the session date. */
  dayNote: string;
};

export type PlaceTimes = Place & {
  periods: TimesPeriod[];
  /** "UTC+3", or "UTC−7 → UTC−8" when the place changes clocks during the cohort. */
  offsetLabel: string;
};

/**
 * Local start/end for every place, grouped into periods of identical times.
 * One period = the same hours on every session day; more than one = the
 * place's hours move part-way through (its clock, or New York's, changes
 * inside the cohort), and each period says from which session date it
 * applies. A place whose offset changes but whose hours don't (Vancouver
 * moves with New York) stays one period; its offsetLabel shows the change.
 */
export const timesByPlace = (
  clock: SessionClock,
  dayIsos: string[],
  places: Place[] = COURSE_PLACES,
): PlaceTimes[] => {
  const starts = sessionStartsUtcMs(clock, dayIsos);
  if (starts.length === 0) return [];
  const dur = Math.max(0, clock.durationMinutes) * MINUTE;
  return places.map((place) => {
    const periods: TimesPeriod[] = [];
    const offsets: string[] = [];
    starts.forEach((s, i) => {
      const localDay = localDateIso(s, place.zone);
      const offset = utcOffsetLabel(s, place.zone);
      if (offsets[offsets.length - 1] !== offset) offsets.push(offset);
      const period: TimesPeriod = {
        fromDayIso: dayIsos[i],
        start: clockTime(s, place.zone),
        end: dur ? clockTime(s + dur, place.zone) : '',
        dayNote: localDay === dayIsos[i] ? '' : localDay > dayIsos[i] ? 'next day' : 'previous day',
      };
      const last = periods[periods.length - 1];
      const same =
        last &&
        last.start === period.start &&
        last.end === period.end &&
        last.dayNote === period.dayNote;
      if (!same) periods.push(period);
    });
    return { ...place, periods, offsetLabel: offsets.join(' → ') };
  });
};

/**
 * Hour-by-hour blocks on the instructor's clock for one session day, e.g.
 * ["09:00 – 10:00", "10:10 – 11:10", ...]. Teaching hours are 60 minutes with
 * a 10-minute break between; [] when the session length is not a whole number
 * of such hours (the page then shows start and end only).
 */
export const hourBlocks = (
  clock: SessionClock,
  dayIso: string,
  zone: string = INSTRUCTOR_ZONE,
  hourMinutes = 60,
  breakMinutes = 10,
): string[] => {
  const [start] = sessionStartsUtcMs(clock, [dayIso]);
  if (start === undefined) return [];
  const n = (clock.durationMinutes + breakMinutes) / (hourMinutes + breakMinutes);
  if (!Number.isInteger(n) || n < 1) return [];
  return Array.from({ length: n }, (_, i) => {
    const a = start + i * (hourMinutes + breakMinutes) * MINUTE;
    return `${clockTime(a, zone, '24h')} – ${clockTime(a + hourMinutes * MINUTE, zone, '24h')}`;
  });
};
