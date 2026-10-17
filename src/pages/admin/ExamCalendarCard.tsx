import React, { useCallback, useEffect, useState } from 'react';
import { CalendarCheck, CalendarClock, Check, Copy, Link2, RefreshCw, X } from 'lucide-react';
import { api, reportError } from './lib';
import { Notice } from './ui';

/* Oral-exam calendar — candidates book their oral examination from the open
 * times on your own calendar.
 *
 * Connected once to Google (your company calendar). Busy time on every
 * calendar listed blocks a slot — add your personal calendar after sharing
 * it with the company account ("See only free/busy"). A booking becomes an
 * event on your company calendar with a Google Meet link, and Google sends
 * the candidate the invitation. Only busy times are read, never what the
 * events are. */

type Settings = {
  connected: boolean;
  account_email: string;
  connected_at: string | null;
  client_id: string;
  client_secret_set: boolean;
  redirect_uri: string;
  check_calendars: string[];
  event_calendar: string;
  timezone: string;
  weekly_hours: Record<string, string[][]>;
  buffer_minutes: number;
  min_notice_hours: number;
  horizon_days: number;
  max_per_day: number;
  step_minutes: number;
  self_booking: boolean;
  last_ok_at: string | null;
  last_error: string;
};

type TestResult = { id: string; ok: boolean; error: string; busy_blocks: number };
type Preview = { timezone: string; count: number; slots: { start: string; label: string }[] };

const DAYS: [string, string][] = [
  ['mon', 'Monday'],
  ['tue', 'Tuesday'],
  ['wed', 'Wednesday'],
  ['thu', 'Thursday'],
  ['fri', 'Friday'],
  ['sat', 'Saturday'],
  ['sun', 'Sunday'],
];

const windowsText = (w: string[][] | undefined) => (w ?? []).map(([a, b]) => `${a}-${b}`).join(', ');

/** "09:00-12:00, 13:00-17:00" → [["09:00","12:00"],["13:00","17:00"]]; '' → [] (day off). */
function parseWindows(text: string): string[][] {
  return text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => part.split(/\s*[-–]\s*/).map((t) => t.trim().padStart(5, '0')));
}

const inputCls =
  'mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-2 py-1.5 text-white text-sm';

export default function ExamCalendarCard({ onAuthError }: { onAuthError: () => void }) {
  const [s, setS] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tests, setTests] = useState<TestResult[] | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [copied, setCopied] = useState(false);
  // Editable copies.
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [hours, setHours] = useState<Record<string, string>>({});
  const [calendars, setCalendars] = useState<string[]>([]);
  const [newCal, setNewCal] = useState('');
  const [nums, setNums] = useState({ buffer: '30', notice: '48', horizon: '21', perDay: '2', step: '30' });
  const [tz, setTz] = useState('America/New_York');
  const [selfBooking, setSelfBooking] = useState(true);

  const adopt = (x: Settings) => {
    setS(x);
    setClientId(x.client_id);
    setHours(Object.fromEntries(DAYS.map(([d]) => [d, windowsText(x.weekly_hours[d])])));
    setCalendars(x.check_calendars.filter((c) => c !== 'primary'));
    setNums({
      buffer: String(x.buffer_minutes),
      notice: String(x.min_notice_hours),
      horizon: String(x.horizon_days),
      perDay: String(x.max_per_day),
      step: String(x.step_minutes),
    });
    setTz(x.timezone);
    setSelfBooking(x.self_booking);
  };

  const load = useCallback(async () => {
    try {
      adopt(await api<Settings>('/api/admin/academy/calendar'));
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
    // Back from Google's consent screen: say how it went, then tidy the URL.
    const q = new URLSearchParams(window.location.search);
    if (q.get('calendar') === 'connected') setFlash('Your calendar is connected.');
    if (q.get('calendar_error')) setError(q.get('calendar_error'));
    if (q.has('calendar') || q.has('calendar_error')) {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.hash}`);
    }
  }, [load]);

  async function run<T>(key: string, fn: () => Promise<T>, done?: string): Promise<T | undefined> {
    setBusy(key);
    setError(null);
    try {
      const out = await fn();
      if (done) {
        setFlash(done);
        window.setTimeout(() => setFlash(null), 6000);
      }
      return out;
    } catch (e) {
      reportError(e, onAuthError, setError);
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  const save = (body: object, done: string) =>
    run(
      'save',
      async () => {
        const x = await api<Settings>('/api/admin/academy/calendar', { method: 'PUT', body: JSON.stringify(body) });
        adopt(x);
        setPreview(null);
        setTests(null);
        return x;
      },
      done,
    );

  if (!s) return error ? <Notice kind="error">{error}</Notice> : null;

  return (
    <section className="card p-5 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <CalendarClock className="w-4 h-4 text-cyan-400" /> Oral-exam calendar
          </h3>
          <p className="text-sm text-slate-300 mt-1 max-w-3xl">
            Candidates who pass the written exam book their oral examination from the open
            times on your calendar. Only busy times are read, never what your events are. A
            booking goes on your calendar with a Google Meet link, and Google sends the
            candidate the invitation.
          </p>
        </div>
        {s.connected ? (
          <span className="text-xs px-2 py-1 rounded-full border border-emerald-700 text-emerald-200 bg-emerald-950/40 inline-flex items-center gap-1">
            <Check className="w-3.5 h-3.5" /> Connected: {s.account_email || 'Google Calendar'}
          </span>
        ) : (
          <span className="text-xs px-2 py-1 rounded-full border border-amber-700 text-amber-200 bg-amber-950/40">
            Not connected: candidates propose times and you confirm one
          </span>
        )}
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {flash && <Notice kind="success">{flash}</Notice>}
      {s.connected && s.last_error && (
        <Notice kind="error">Last problem reading your calendar: {s.last_error}</Notice>
      )}

      {/* ---- Connection ---- */}
      {!s.connected && (
        <div className="rounded-lg border border-slate-800 p-4 space-y-3">
          <div className="text-xs uppercase tracking-wider text-slate-400">Connect Google Calendar</div>
          <ol className="text-sm text-slate-300 list-decimal list-inside space-y-1">
            <li>
              In Google Cloud (signed in as your company account), create an OAuth client of type
              "Web application" with this authorized redirect URI:
            </li>
          </ol>
          <div className="flex items-center gap-2">
            <code className="text-xs text-cyan-200 bg-slate-950/70 border border-slate-800 rounded px-2 py-1 break-all">
              {s.redirect_uri}
            </code>
            <button
              type="button"
              className="btn-ghost text-xs"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(s.redirect_uri);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                } catch {
                  /* visible on screen anyway */
                }
              }}
            >
              {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />} {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <ol start={2} className="text-sm text-slate-300 list-decimal list-inside space-y-1">
            <li>Paste its client ID and client secret here and save.</li>
            <li>Press Connect and allow both calendar permissions on Google's screen.</li>
          </ol>
          <div className="grid md:grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Client ID</span>
              <input value={clientId} onChange={(e) => setClientId(e.target.value)} className={inputCls} autoComplete="off" />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">
                Client secret {s.client_secret_set && <span className="normal-case text-emerald-300">(saved; paste a new one to replace it)</span>}
              </span>
              <input
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                className={inputCls}
                autoComplete="new-password"
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary text-sm py-2 px-4"
              disabled={busy === 'save' || (!clientId && !clientSecret)}
              onClick={() =>
                void save(
                  { client_id: clientId, ...(clientSecret ? { client_secret: clientSecret } : {}) },
                  'OAuth client saved.',
                ).then(() => setClientSecret(''))
              }
            >
              Save the OAuth client
            </button>
            <button
              type="button"
              className="btn-primary text-sm py-2 px-4"
              disabled={busy === 'connect' || !s.client_id || !s.client_secret_set}
              onClick={() =>
                void run('connect', async () => {
                  const { url } = await api<{ url: string }>('/api/admin/academy/calendar/connect', { method: 'POST' });
                  window.location.href = url;
                })
              }
            >
              <Link2 className="w-4 h-4" /> Connect Google Calendar
            </button>
          </div>
        </div>
      )}

      {/* ---- Calendars checked ---- */}
      <div className="grid md:grid-cols-2 gap-5">
        <div className="space-y-3">
          <div className="text-xs uppercase tracking-wider text-slate-400">Calendars that block a time when busy</div>
          <ul className="space-y-1.5 text-sm">
            <li className="flex items-center gap-2 text-slate-200">
              <CalendarCheck className="w-4 h-4 text-cyan-400" />
              {s.account_email || 'Your connected calendar'} <span className="text-xs text-slate-500">(exams are added here)</span>
            </li>
            {calendars.map((c) => (
              <li key={c} className="flex items-center gap-2 text-slate-200">
                <CalendarCheck className="w-4 h-4 text-cyan-400" /> {c}
                <button
                  type="button"
                  className="btn-ghost text-xs text-red-300"
                  title="Stop checking this calendar"
                  onClick={() => setCalendars(calendars.filter((x) => x !== c))}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </li>
            ))}
          </ul>
          <div className="flex items-end gap-2">
            <label className="block flex-1">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Add a calendar (its email address)</span>
              <input
                value={newCal}
                onChange={(e) => setNewCal(e.target.value)}
                placeholder="you@gmail.com"
                className={inputCls}
              />
            </label>
            <button
              type="button"
              className="btn-ghost text-xs mb-1"
              disabled={!newCal.includes('@')}
              onClick={() => {
                setCalendars([...new Set([...calendars, newCal.trim()])]);
                setNewCal('');
              }}
            >
              Add
            </button>
          </div>
          <p className="text-xs text-slate-400">
            A personal calendar must first be shared with {s.account_email || 'the connected account'}: in
            that calendar's settings, "Share with specific people", permission "See only free/busy".
            Use "Test the calendars" to check.
          </p>
          <label className="flex items-center gap-2 text-sm text-slate-200">
            <input type="checkbox" checked={selfBooking} onChange={(e) => setSelfBooking(e.target.checked)} className="accent-cyan-400" />
            Candidates book their own time (off: they propose windows and you confirm one)
          </label>
        </div>

        {/* ---- Exam hours and rules ---- */}
        <div className="space-y-3">
          <div className="text-xs uppercase tracking-wider text-slate-400">
            Exam hours on your clock — blank is a day off; several windows: 09:00-12:00, 13:00-17:00
          </div>
          <div className="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-1.5 items-center">
            {DAYS.map(([d, label]) => (
              <React.Fragment key={d}>
                <span className="text-sm text-slate-300">{label}</span>
                <input
                  value={hours[d] ?? ''}
                  onChange={(e) => setHours({ ...hours, [d]: e.target.value })}
                  placeholder="day off"
                  className="rounded-lg bg-slate-950/70 border border-slate-700 px-2 py-1 text-white text-sm font-mono"
                />
              </React.Fragment>
            ))}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Time zone</span>
              <input value={tz} onChange={(e) => setTz(e.target.value)} className={inputCls} />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Gap around exams (min)</span>
              <input type="number" min={0} max={240} value={nums.buffer} onChange={(e) => setNums({ ...nums, buffer: e.target.value })} className={inputCls} />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Minimum notice (hours)</span>
              <input type="number" min={1} max={720} value={nums.notice} onChange={(e) => setNums({ ...nums, notice: e.target.value })} className={inputCls} />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Bookable ahead (days)</span>
              <input type="number" min={1} max={120} value={nums.horizon} onChange={(e) => setNums({ ...nums, horizon: e.target.value })} className={inputCls} />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Exams per day (0 = no limit)</span>
              <input type="number" min={0} max={10} value={nums.perDay} onChange={(e) => setNums({ ...nums, perDay: e.target.value })} className={inputCls} />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-300">Start times every</span>
              <select value={nums.step} onChange={(e) => setNums({ ...nums, step: e.target.value })} className={inputCls}>
                <option value="15">15 minutes</option>
                <option value="30">30 minutes</option>
                <option value="60">hour</option>
              </select>
            </label>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          className="btn-primary text-sm py-2 px-4"
          disabled={busy === 'save'}
          onClick={() =>
            void save(
              {
                check_calendars: ['primary', ...calendars],
                weekly_hours: Object.fromEntries(DAYS.map(([d]) => [d, parseWindows(hours[d] ?? '')])),
                timezone: tz.trim(),
                buffer_minutes: Number(nums.buffer),
                min_notice_hours: Number(nums.notice),
                horizon_days: Number(nums.horizon),
                max_per_day: Number(nums.perDay),
                step_minutes: Number(nums.step),
                self_booking: selfBooking,
              },
              'Calendar settings saved.',
            )
          }
        >
          Save calendar settings
        </button>
        <button
          type="button"
          className="btn-secondary text-sm py-2 px-4"
          disabled={!s.connected || busy === 'test'}
          onClick={() =>
            void run('test', async () => {
              const r = await api<{ calendars: TestResult[] }>('/api/admin/academy/calendar/test', { method: 'POST' });
              setTests(r.calendars);
            })
          }
        >
          <RefreshCw className="w-4 h-4" /> Test the calendars
        </button>
        <button
          type="button"
          className="btn-secondary text-sm py-2 px-4"
          disabled={!s.connected || busy === 'preview'}
          onClick={() =>
            void run('preview', async () => setPreview(await api<Preview>('/api/admin/academy/calendar/preview')))
          }
        >
          <CalendarClock className="w-4 h-4" /> Preview open times
        </button>
        {s.connected && (
          <button
            type="button"
            className="btn-ghost text-sm text-red-300 ml-auto"
            disabled={busy === 'disconnect'}
            onClick={() => {
              if (!window.confirm('Disconnect your calendar? Candidates will propose times again until you reconnect.')) return;
              void run('disconnect', async () => adopt(await api<Settings>('/api/admin/academy/calendar/disconnect', { method: 'POST' })), 'Calendar disconnected.');
            }}
          >
            Disconnect
          </button>
        )}
      </div>

      {tests && (
        <ul className="text-sm space-y-1">
          {tests.map((t) => (
            <li key={t.id} className={t.ok ? 'text-emerald-300' : 'text-red-300'}>
              {t.ok ? '✓' : '✗'} {t.id === 'primary' ? s.account_email || 'Your calendar' : t.id}:{' '}
              {t.ok
                ? `readable (${t.busy_blocks} busy block${t.busy_blocks === 1 ? '' : 's'} in the next 7 days)`
                : `cannot be read (${t.error}). Share it with ${s.account_email} as "See only free/busy".`}
            </li>
          ))}
        </ul>
      )}

      {preview && (
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-400">
            What a candidate is offered now: {preview.count} open time{preview.count === 1 ? '' : 's'} ({preview.timezone})
          </div>
          {preview.count === 0 ? (
            <p className="text-sm text-amber-200 mt-1">No open times: check your exam hours and calendars.</p>
          ) : (
            <ul className="mt-1 grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-0.5 text-sm text-slate-200">
              {preview.slots.map((x) => (
                <li key={x.start}>{x.label}</li>
              ))}
            </ul>
          )}
          {preview.count > preview.slots.length && (
            <p className="text-xs text-slate-500 mt-1">…and {preview.count - preview.slots.length} more.</p>
          )}
        </div>
      )}
    </section>
  );
}
