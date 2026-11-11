import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  CircleSlash,
  CreditCard,
  Search,
  Settings,
  Undo2,
  UserX,
  Video,
  XCircle,
} from 'lucide-react';
import { api, formatDate, money, reportError, type ViewState } from './lib';
import { EmptyState, Notice, RefreshButton, Section } from './ui';

/* Consulting — paid expert calls booked from /consult.
 *
 * Status strip (calendar, Meet attendance scope, Stripe, booking on/off,
 * next open time), the bookings list (search + status filter), one booking
 * with its timeline and the money actions, and the settings form.
 *
 * Every money action sits behind a confirmation that states the amount.
 * Text is never truncated: names, emails and topics wrap. */

// ----- Wire types -------------------------------------------------------------

type Tier = 'same_day' | 'next_day' | 'priority' | 'standard';
const TIERS: { key: Tier; label: string; hint: string }[] = [
  { key: 'same_day', label: 'Same day', hint: 'call on the booking date' },
  { key: 'next_day', label: 'Next day', hint: 'call the day after' },
  { key: 'priority', label: 'Priority', hint: '2 days ahead up to the standard threshold' },
  { key: 'standard', label: 'Standard', hint: 'from the threshold below' },
];

const STATUSES = ['pending_card', 'confirmed', 'completed', 'no_show', 'cancelled', 'expired'] as const;
type Status = (typeof STATUSES)[number];

const STATUS_LABEL: Record<string, string> = {
  pending_card: 'Waiting for card',
  confirmed: 'Confirmed',
  completed: 'Completed',
  no_show: 'No-show',
  cancelled: 'Cancelled',
  expired: 'Expired',
};
const STATUS_TONE: Record<string, string> = {
  pending_card: 'bg-amber-500/20 text-amber-200 border-amber-500/40',
  confirmed: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
  completed: 'bg-cyan-500/20 text-cyan-200 border-cyan-500/40',
  no_show: 'bg-red-500/20 text-red-200 border-red-500/40',
  cancelled: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
  expired: 'bg-slate-600/20 text-slate-300 border-slate-600/40',
};

type Attendance =
  | string
  | {
      state?: string;
      host_joined?: boolean | null;
      others_joined?: number | null;
      participants?: string[];
      checked_at?: string | null;
      note?: string;
    }
  | null;

type TimelineEvent = {
  at: string;
  kind?: string;
  type?: string;
  detail?: string;
  message?: string;
  actor?: string;
  cents?: number | null;
};

export type ConsultBooking = {
  id: number;
  ref: string;
  status: Status | string;
  start: string;
  end?: string | null;
  minutes: number;
  timezone: string;
  full_name: string;
  email: string;
  company?: string | null;
  phone?: string | null;
  topic: string;
  tier: Tier | string;
  tier_label?: string;
  rate_cents_per_hour: number;
  total_cents: number;
  fee_percent?: number;
  fee_cents: number;
  payment_state?: string | null;
  hold_state?: string | null;
  charged_cents: number | null;
  refunded_cents?: number | null;
  /** The SAVED card (second review fixes, D). */
  card_brand?: string | null;
  card_last4?: string | null;
  /** The card the hold is on or the money was taken from; null while none is held or taken. */
  money_card_brand?: string | null;
  money_card_last4?: string | null;
  /** The money ledger, one row per Stripe attempt (card per row since the second review fixes). */
  charges?: {
    id: number | string;
    kind: string;
    reason?: string;
    attempt?: number;
    status: string;
    amount_cents: number;
    captured_cents?: number | null;
    error_code?: string;
    decline_code?: string;
    error_message?: string;
    card_brand?: string | null;
    card_last4?: string | null;
    actor?: string;
    note?: string;
    created_at: string;
  }[];
  attendance?: Attendance;
  meet_url?: string | null;
  settle_due_at?: string | null;
  created_at?: string | null;
  consent?: {
    terms_version?: string;
    terms_hash?: string;
    at?: string;
    ip?: string;
    user_agent?: string;
  } | null;
  events?: TimelineEvent[];
  /** What the server will accept now (W1a). */
  actions?: {
    can_charge: boolean;
    can_no_show: boolean;
    can_waive: boolean;
    can_cancel: boolean;
    can_refund: boolean;
    refundable_cents: number;
    /** W1b: an attempt with an unknown outcome waits to be checked in Stripe. */
    can_review?: boolean;
  };
  /** W1b: charged - refunded - lost to a dispute (never below 0). */
  kept_cents?: number;
  disputed_cents?: number;
  dispute_lost_cents?: number;
  dispute_state?: '' | 'open' | 'lost' | 'won' | 'closed' | string;
  needs_review?: {
    charge_id: number | string;
    kind: 'charge' | 'hold' | string;
    reason: string;
    amount_cents: number;
    created_at: string;
  }[];
  /** W1b: '' | pending | paid | failed | requires_action | review (an attempt parked for
   *  the owner: NOT a refused card) | open (owed, nothing in flight, no card refused). */
  charge_state?: string | null;
  charge_error?: string | null;
  hold_error?: string | null;
  cancel_fee_cents?: number | null;
  settlement?: string | null;
  business_timezone?: string | null;
};

/** Answer of every admin money action: the booking plus what Stripe said. */
type ActionResult = ConsultBooking & {
  action?: { ok: boolean; status: string; amount_cents: number; code: string; message: string };
};

const PAYMENT_LABEL: Record<string, string> = {
  no_card: 'no card yet',
  card_saved: 'card saved',
  hold_placed: 'hold placed',
  hold_failed: 'hold refused',
  payment_pending: 'payment being confirmed by Stripe',
  paid: 'paid',
  payment_failed: 'payment refused',
  not_charged: 'not charged',
  partly_refunded: 'partly refunded',
  refunded: 'refunded',
};
const REASON_LABEL: Record<string, string> = {
  meeting: 'the call',
  no_show_fee: 'the no-show fee',
  late_cancel_fee: 'the late-cancellation fee',
  hold: 'the card hold',
};

/** The dispute fields in words, or '' when there has never been one. */
function disputeText(b: { dispute_state?: string; disputed_cents?: number; dispute_lost_cents?: number }): string {
  const held = b.disputed_cents ?? 0;
  const lost = b.dispute_lost_cents ?? 0;
  switch (b.dispute_state) {
    case 'open':
      return `Open at the client's bank: ${money(held)} held by the dispute${lost ? `, ${money(lost)} already lost` : ''}. It cannot be refunded from here.`;
    case 'lost':
      return `Lost: the bank gave ${money(lost)} back to the cardholder.`;
    case 'won':
      return 'Won: the bank kept nothing back.';
    case 'closed':
      return 'Bank inquiry closed: nothing was taken back.';
    case '':
    case undefined:
    case null:
      return '';
    default:
      return String(b.dispute_state);
  }
}

const paymentText = (s?: string | null) => (s ? PAYMENT_LABEL[s] ?? s.replace(/_/g, ' ') : 'no payment yet');

/** The payment state in words for one booking. `payment_failed` covers three
 *  charge states (W1b review fixes): only failed / requires_action mean the
 *  card was refused; `review` is an attempt being checked, `open` is owed. */
function paymentWords(b: { payment_state?: string | null; charge_state?: string | null }): string {
  if (b.charge_state === 'review') return 'payment being checked (outcome unknown)';
  if (b.charge_state === 'open') return 'owed, not charged yet';
  if (b.charge_state === 'requires_action') return 'payment refused (the card needs the client\'s authentication)';
  return paymentText(b.payment_state);
}

/** charge_error with a label that fits the charge state. */
function chargeErrorLine(b: { charge_state?: string | null; charge_error?: string | null }): { label: string; tone: string } | null {
  if (!b.charge_error) return null;
  switch (b.charge_state) {
    case 'failed':
    case 'requires_action':
      return { label: 'Charge refused: ', tone: 'text-red-300' };
    case 'review':
      return { label: 'Being checked. Stripe\'s last answer: ', tone: 'text-amber-200' };
    case 'open':
      return { label: '', tone: 'text-slate-300' };
    default:
      return { label: 'Stripe\'s last answer: ', tone: 'text-slate-300' };
  }
}

type ConsultSettings = {
  enabled: boolean;
  timezone: string;
  weekly_hours: Record<string, string[][]>;
  step_minutes: number;
  durations: number[];
  buffer_minutes: number;
  min_notice_hours: number;
  horizon_days: number;
  max_per_day: number;
  /** A tier may be unset (null): booking stays off until the owner saves all four. */
  rates_cents_per_hour: Record<Tier, number | null>;
  standard_from_days: number;
  fee_percent: number;
  free_cancel_hours: number;
  hold_lead_hours: number;
  auto_settle_hours: number;
  /** Reminder lead times (W1b): first before the free-cancellation deadline, last before the start. */
  reminder_before_deadline_hours: number;
  reminder_before_start_hours: number;
  /** Read-only (W1b): every hourly rate is set (> 0). */
  rates_set?: boolean;
};

type ConsultStatus = {
  calendar_ok: boolean;
  meet_scope_ok: boolean;
  stripe_ok: boolean;
  enabled: boolean;
  next_available: { start: string; tier: string } | null;
  calendar_error?: string;
  calendar_account?: string;
  /** W1b: every hourly rate is set; `enabled` = switched on AND rates set. */
  rates_set?: boolean;
  /** W1b: the settlement tick ran to the end in the last 30 minutes. */
  tick_ok?: boolean;
  last_tick_at?: string | null;
  /** W1b review fixes: ended calls whose "confirm the outcome" email has not gone out. */
  summaries_unsent?: number;
  summaries_unsent_since?: string | null;
  summaries_unsent_note?: string;
};

// ----- Small helpers ----------------------------------------------------------

const tierName = (t: string, label?: string) => label || TIERS.find((x) => x.key === t)?.label || t;

const minutesText = (m: number) => {
  const h = Math.floor(m / 60);
  const r = m % 60;
  return [h ? `${h} h` : '', r ? `${r} min` : ''].filter(Boolean).join(' ') || '0 min';
};

/** "Tue, Nov 10, 2026, 3:30 PM EST" in a given zone. */
const inZone = (iso: string, tz: string) => {
  try {
    return new Date(iso).toLocaleString('en-US', {
      timeZone: tz,
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    });
  } catch {
    return formatDate(iso);
  }
};

const cardWords = (brand?: string | null, last4?: string | null) =>
  last4 ? `${(brand || 'card').toUpperCase()} ending ${last4}` : '';
/** The card a capture, fee or refund uses: the one the hold is on or the money
 *  was taken from when there is one, else the saved card. */
const cardText = (b: ConsultBooking) =>
  cardWords(b.money_card_brand, b.money_card_last4) || cardWords(b.card_brand, b.card_last4) || 'the saved card';
/** "Hold on" / "Charged to" a card other than the saved one, or null when they are the same. */
function moneyCardLine(b: ConsultBooking): string | null {
  const money = cardWords(b.money_card_brand, b.money_card_last4);
  if (!money || money === cardWords(b.card_brand, b.card_last4)) return null;
  return `${(b.charged_cents ?? 0) > 0 ? 'Charged to' : 'Hold on'}: ${money}`;
}

/** action.code values that are not a refused card: shown as the server says, in amber. */
const NOT_A_REFUSAL = new Set(['capture_unconfirmed', 'unrecorded', 'stripe_wait', 'refund_pending', 'request_refused', 'decision_changed', 'not_owed']);

const LEDGER_KIND: Record<string, string> = { hold: 'Hold', charge: 'Charge', capture: 'Capture', refund: 'Refund', release: 'Release' };

const ATTENDANCE_LABEL: Record<string, string> = {
  both: 'you and the client joined',
  client_absent: 'you joined, the client did not',
  host_absent: 'you did not join',
  unknown: 'unknown',
};

/** Attendance in one line. The participant lines are listed separately (participantLines). */
function attendanceText(a: Attendance | undefined): string {
  if (!a) return 'unknown';
  if (typeof a === 'string') return ATTENDANCE_LABEL[a] ?? a.replace(/_/g, ' ');
  const parts: string[] = [];
  if (a.state) parts.push(ATTENDANCE_LABEL[a.state] ?? a.state.replace(/_/g, ' '));
  if (a.host_joined !== undefined && a.host_joined !== null) parts.push(a.host_joined ? 'host joined' : 'host did not join');
  if (a.others_joined !== undefined && a.others_joined !== null) parts.push(`${a.others_joined} other participant${a.others_joined === 1 ? '' : 's'} counted`);
  if (a.checked_at) parts.push(`checked ${formatDate(a.checked_at)}`);
  if (a.note) parts.push(a.note);
  return parts.join(' · ') || 'unknown';
}

/** Who joined: the server's ready-to-show sentences, one per person. */
const participantLines = (a: Attendance | undefined): string[] =>
  a && typeof a === 'object' && Array.isArray(a.participants) ? a.participants.map(String).filter((x) => x.trim()) : [];

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border whitespace-nowrap ${
        STATUS_TONE[status] ?? 'bg-slate-700/30 text-slate-300 border-slate-600/40'
      }`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

const inputCls =
  'w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500';
const labelCls = 'text-[11px] uppercase tracking-wider text-slate-300 mb-1 block';

// ----- Status strip -----------------------------------------------------------

function StatusStrip({ s, openSettings }: { s: ConsultStatus | null; openSettings: () => void }) {
  if (!s) return null;
  const ratesSet = s.rates_set !== false;
  // Why clients cannot book right now, and what to do about each, in order.
  const blockers: { why: string; todo: string }[] = [];
  if (!ratesSet) blockers.push({ why: 'the hourly rates are not set', todo: 'enter all four rates in Settings and save' });
  if (ratesSet && !s.enabled) blockers.push({ why: 'booking is switched off', todo: 'turn the "Booking is open" switch on in Settings and save' });
  if (!s.calendar_ok) blockers.push({ why: 'your calendar cannot be read', todo: 'reconnect the calendar on the Certification page (exam calendar card)' });
  if (!s.stripe_ok) blockers.push({ why: 'Stripe is not configured', todo: 'add the Stripe keys to the API settings' });
  const chip = (ok: boolean, good: string, bad: string, key: string) => (
    <span
      key={key}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${
        ok
          ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
          : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
      }`}
    >
      {ok ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0" /> : <XCircle className="w-3.5 h-3.5 shrink-0" />}
      {ok ? good : bad}
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="consult-status">
      {chip(s.enabled, 'Booking is on', 'Booking is off: /consult shows "temporarily unavailable"', 'enabled')}
      {chip(ratesSet, 'Rates set', 'Rates not set', 'rates')}
      {chip(
        s.calendar_ok,
        `Calendar readable${s.calendar_account ? ` (${s.calendar_account})` : ''}`,
        `Calendar cannot be read: every slot is blocked${s.calendar_error ? `. Google says: ${s.calendar_error}` : ''}`,
        'cal',
      )}
      {chip(s.meet_scope_ok, 'Meet attendance readable', 'Meet attendance scope not granted: attendance stays "unknown"', 'meet')}
      {chip(s.stripe_ok, 'Stripe connected', 'Stripe not configured: no card can be saved', 'stripe')}
      {chip(
        Boolean(s.tick_ok),
        `Automation running (last run ${s.last_tick_at ? formatDate(s.last_tick_at) : 'just now'})`,
        s.last_tick_at
          ? `Automation stopped: the cron job has not called in since ${formatDate(s.last_tick_at)}. No holds, reminders or automatic charges until it does`
          : 'Automation stopped: the cron job has never called in. No holds, reminders or automatic charges until it does',
        'tick',
      )}
      <span className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-1.5 text-xs text-slate-200">
        <CalendarClock className="w-3.5 h-3.5 shrink-0 text-cyan-400" />
        {s.next_available
          ? `Next open: ${formatDate(s.next_available.start)} (${tierName(s.next_available.tier)})`
          : 'No open time'}
      </span>
      {(s.summaries_unsent ?? 0) > 0 && (
        <div role="alert" data-testid="consult-summaries-unsent" className="basis-full rounded-lg border border-amber-500/40 bg-amber-950/40 px-3 py-2.5 text-sm text-amber-100">
          <p className="font-semibold">
            {s.summaries_unsent === 1
              ? 'One call has ended without its "confirm the outcome" email being sent'
              : `${s.summaries_unsent} calls have ended without their "confirm the outcome" email being sent`}
            {s.summaries_unsent_since ? ` (the ${s.summaries_unsent === 1 ? 'call' : 'oldest'} ended ${formatDate(s.summaries_unsent_since)})` : ''}.
          </p>
          <p className="mt-1">
            {s.summaries_unsent_note ||
              'Nothing is charged automatically for these calls until the email has gone out: decide each one from its booking.'}
          </p>
        </div>
      )}
      {blockers.length > 0 && (
        <div role="status" data-testid="consult-cannot-book" className="basis-full rounded-lg border border-amber-500/40 bg-amber-950/40 px-3 py-2.5 text-sm text-amber-100">
          <p className="font-semibold">Clients cannot book right now.</p>
          <ul className="mt-1 list-disc pl-5 space-y-0.5">
            {blockers.map((b) => (
              <li key={b.why}>
                Because {b.why}: {b.todo}.
              </li>
            ))}
          </ul>
          {(!ratesSet || !s.enabled) && (
            <button type="button" onClick={openSettings} className="btn-ghost mt-2">
              <Settings className="w-4 h-4" /> Open Settings
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ----- Bookings list ----------------------------------------------------------

function BookingsList({
  onAuthError,
  open,
}: {
  onAuthError: () => void;
  open: (id: number) => void;
}) {
  const [rows, setRows] = useState<ConsultBooking[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (status) params.set('status', status);
      if (query) params.set('q', query);
      const qs = params.toString();
      const r = await api<{ bookings: ConsultBooking[] }>(`/api/admin/consult/bookings${qs ? `?${qs}` : ''}`);
      setRows(r.bookings ?? []);
      setError(null);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError, status, query]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(q.trim());
        }}
        role="search"
      >
        <label className="block flex-1 min-w-[14rem]">
          <span className={labelCls}>Search</span>
          <span className="relative block">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Name, email, company, ref or topic"
              className={`${inputCls} pl-9`}
              aria-label="Search bookings"
            />
          </span>
        </label>
        <label className="block">
          <span className={labelCls}>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputCls} aria-label="Filter by status">
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn-secondary text-sm py-2 px-3">
          <Search className="w-4 h-4" /> Search
        </button>
        <RefreshButton onClick={() => void load()} loading={loading} />
      </form>

      {error && <Notice kind="error">{error}</Notice>}

      {rows && rows.length === 0 && (
        <EmptyState
          icon={<CalendarClock className="w-5 h-5" />}
          title={status || query ? 'No bookings match' : 'No bookings yet'}
          hint={status || query ? 'Try another search or status.' : 'Bookings made on /consult appear here.'}
        />
      )}

      {rows && rows.length > 0 && (
        <ul className="space-y-2" data-testid="consult-bookings">
          {rows.map((b) => (
            <li key={b.id}>
              <button
                type="button"
                onClick={() => open(b.id)}
                className="w-full text-left bg-slate-900/70 border border-slate-800 hover:border-cyan-500/40 rounded-xl p-4 transition-colors"
              >
                <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_minmax(0,1fr)] gap-x-6 gap-y-2">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-white break-words">{formatDate(b.start)}</div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      {minutesText(b.minutes)} · {tierName(b.tier, b.tier_label)} · ref {b.ref}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm text-slate-100 break-words">
                      {b.full_name}
                      {b.company ? <span className="text-slate-400"> · {b.company}</span> : null}
                    </div>
                    <div className="text-xs text-slate-400 break-all">{b.email}</div>
                    <div className="text-xs text-slate-300 mt-1 break-words whitespace-pre-wrap">{b.topic}</div>
                  </div>
                  <div className="min-w-0 flex flex-col md:items-end gap-1">
                    <StatusPill status={b.status} />
                    <div className="text-sm text-white tabular-nums">{money(b.total_cents)}</div>
                    <div className="text-xs text-slate-400 break-words md:text-right">
                      {b.charged_cents
                        ? `charged ${money(b.charged_cents)}${b.refunded_cents ? `, refunded ${money(b.refunded_cents)}` : ''}`
                        : paymentWords(b)}
                      {b.dispute_state === 'open' || b.dispute_state === 'lost' ? ` · dispute ${b.dispute_state}` : ''}
                      {(b.needs_review?.length ?? 0) > 0 ? ' · check in Stripe' : ''}
                    </div>
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ----- One booking ------------------------------------------------------------

function BookingDetail({
  id,
  onAuthError,
  back,
  onChanged,
}: {
  id: number;
  onAuthError: () => void;
  back: () => void;
  onChanged: () => void;
}) {
  const [b, setB] = useState<ConsultBooking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [warn, setWarn] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [chargeMinutes, setChargeMinutes] = useState<number | null>(null);
  const [refundDollars, setRefundDollars] = useState('');
  const [cancelNote, setCancelNote] = useState('');
  const [reviewDollars, setReviewDollars] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const r = await api<ConsultBooking>(`/api/admin/consult/bookings/${id}`);
      setB(r);
      setChargeMinutes((m) => m ?? r.minutes);
      setError(null);
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }, [id, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(key: string, path: string, body: unknown, done: (amountCents: number | null) => string) {
    setBusy(key);
    setError(null);
    setWarn(null);
    setFlash(null);
    try {
      const r = await api<ActionResult>(`/api/admin/consult/bookings/${id}/${path}`, {
        method: 'POST',
        body: JSON.stringify(body ?? {}),
      });
      const { action, ...booking } = r;
      setB(booking);
      if (action && action.ok === false && NOT_A_REFUSAL.has(action.code)) {
        // Not a refused card (still being confirmed, not recorded, waiting on Stripe): the server's sentence, in amber.
        setWarn(action.message || 'Stripe has not confirmed this yet.');
      } else if (action && action.ok === false) {
        // The card did not pay (declined, needs authentication, Stripe down).
        setError(action.message || 'The payment did not go through.');
      } else if (action && action.status === 'noop' && action.message) {
        // Nothing new was done (e.g. "This refund was already made a moment ago."): say so as the server does.
        setFlash(action.message);
      } else {
        setFlash(done(action ? action.amount_cents : null));
      }
      onChanged();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  const minuteOptions = useMemo(() => {
    if (!b) return [];
    // The server bills at most the booked length (what the client agreed to).
    const out: number[] = [];
    for (let m = 30; m <= b.minutes; m += 30) out.push(m);
    return out;
  }, [b]);

  if (error && !b) {
    return (
      <div className="space-y-4">
        <button type="button" onClick={back} className="btn-ghost">
          <ArrowLeft className="w-4 h-4" /> All bookings
        </button>
        <Notice kind="error">{error}</Notice>
      </div>
    );
  }
  if (!b) return <p className="text-sm text-slate-400">Loading booking…</p>;

  const charged = b.charged_cents ?? 0;
  const refunded = b.refunded_cents ?? 0;
  const rawA = b.actions ?? {
    can_charge: false, can_no_show: false, can_waive: false, can_cancel: false, can_refund: false,
    refundable_cents: Math.max(0, charged - refunded),
  };
  // A payment Stripe has not confirmed yet (e.g. capture_unconfirmed): the tick
  // finishes it, and no other outcome can be chosen meanwhile.
  const confirmingPay = b.charge_state === 'pending';
  const A = confirmingPay ? { ...rawA, can_charge: false, can_no_show: false, can_waive: false } : rawA;
  const refundable = A.refundable_cents;
  const notStarted = b.status === 'confirmed' && Date.now() < new Date(b.start).getTime();
  /** Why a settle button is off, in words. */
  const settleWhy = (): string => {
    if (confirmingPay) return 'Stripe has not confirmed the last payment yet. The site checks again within a few minutes; Charge, No-show and Do not charge stay unavailable until then.';
    if (notStarted) return `Available from the start time (${formatDate(b.start)}). To call it off before then, cancel it.`;
    if (b.status === 'pending_card') return 'No card has been saved yet.';
    if (b.status === 'expired') return 'The booking expired before it was confirmed.';
    if (b.status === 'cancelled') return 'The booking is cancelled.';
    if (charged > 0) return `Already settled: ${paymentWords(b)}. To give money back, refund.`;
    return 'Not available in this state.';
  };
  const cancelWhy = b.status === 'cancelled' ? 'Already cancelled.' : b.status === 'expired' ? 'The booking expired.' : 'The call has taken place; settle it instead.';
  const Why = ({ show, children }: { show: boolean; children: React.ReactNode }) =>
    show ? <p className="text-xs text-amber-200/90">{children}</p> : null;
  const chargeCents = chargeMinutes ? Math.round((b.rate_cents_per_hour * chargeMinutes) / 60) : 0;
  const feePct = b.fee_percent ?? (b.total_cents ? Math.round((b.fee_cents / b.total_cents) * 100) : 0);
  const refundCents = Math.round(Number(refundDollars || '0') * 100);
  const who = `${b.full_name} (${b.email})`;

  const actionBtn = 'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold border transition-colors disabled:opacity-50 disabled:cursor-not-allowed';

  const confirmThen = (msg: string, fn: () => void) => {
    if (window.confirm(msg)) fn();
  };

  const events = [...(b.events ?? [])].sort((x, y) => (x.at < y.at ? 1 : -1));
  // The call has ended (10 min ago or more, as the server counts it), nothing is
  // decided, and the timeline has no summary_sent: no automatic outcome runs yet.
  const endMs = b.end ? new Date(b.end).getTime() : new Date(b.start).getTime() + b.minutes * 60_000;
  const summaryWaiting =
    b.status === 'confirmed' &&
    !b.settlement &&
    Date.now() >= endMs + 10 * 60_000 &&
    !(b.events ?? []).some((e) => (e.kind || e.type) === 'summary_sent');

  return (
    // Bottom padding keeps the last card clear of the floating "Ask the assistant" button.
    <div className="space-y-6 pb-24" data-testid="consult-detail">
      <button type="button" onClick={back} className="btn-ghost">
        <ArrowLeft className="w-4 h-4" /> All bookings
      </button>

      {error && <div role="alert"><Notice kind="error">{error}</Notice></div>}
      {warn && <div role="alert" data-testid="consult-warn"><Notice kind="warn">{warn}</Notice></div>}
      {flash && <div role="status"><Notice kind="success">{flash}</Notice></div>}

      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold text-white break-words">{b.full_name}</h3>
            <p className="text-sm text-slate-300 break-all">{b.email}</p>
            {(b.company || b.phone) && (
              <p className="text-sm text-slate-400 break-words">{[b.company, b.phone].filter(Boolean).join(' · ')}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <StatusPill status={b.status} />
            <span className="font-mono text-xs text-slate-400">ref {b.ref}</span>
          </div>
        </div>

        <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3 text-sm">
          <div>
            <dt className="text-slate-400">When (your clock)</dt>
            <dd className="text-slate-100">{formatDate(b.start)} · {minutesText(b.minutes)}</dd>
          </div>
          <div>
            <dt className="text-slate-400">When (client's zone, {b.timezone})</dt>
            <dd className="text-slate-100 break-words">{inZone(b.start, b.timezone)}</dd>
          </div>
          <div>
            <dt className="text-slate-400">Tier and rate</dt>
            <dd className="text-slate-100">
              {tierName(b.tier, b.tier_label)} · {money(b.rate_cents_per_hour)} per hour
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">Booked amount · no-show / late fee</dt>
            <dd className="text-slate-100 tabular-nums">
              {money(b.total_cents)} · {money(b.fee_cents)} ({feePct}%)
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">Payment</dt>
            <dd className="text-slate-100 break-words">
              <span data-testid="consult-payment-state">{paymentWords(b)}</span>
              {b.hold_state ? ` · hold ${b.hold_state.replace(/_/g, ' ')}` : ''}
              {' · '}charged {money(charged)}
              {refunded ? ` · refunded ${money(refunded)}` : ''}
              {typeof b.kept_cents === 'number' && <span className="block font-semibold" data-testid="consult-kept">Kept: {money(b.kept_cents)}</span>}
              {(() => {
                const line = chargeErrorLine(b);
                return line ? (
                  <span className={`block ${line.tone}`} data-testid="consult-charge-error">
                    {line.label}
                    {b.charge_error}
                  </span>
                ) : null;
              })()}
              {b.charge_state === 'review' && (b.needs_review?.length ?? 0) === 0 && (
                <span className="block text-amber-200">Check this payment in Stripe before charging again.</span>
              )}
              {b.hold_error ? <span className="block text-amber-200">Hold refused: {b.hold_error}</span> : null}
            </dd>
          </div>
          {disputeText(b) && (
            <div className="md:col-span-2">
              <dt className="text-slate-400">Dispute</dt>
              <dd className={`break-words ${b.dispute_state === 'open' || b.dispute_state === 'lost' ? 'text-amber-200' : 'text-slate-100'}`} data-testid="consult-dispute">
                {disputeText(b)}
              </dd>
            </div>
          )}
          <div>
            <dt className="text-slate-400">Card</dt>
            <dd className="text-slate-100 break-words">
              <span data-testid="consult-saved-card">{b.card_last4 ? `${cardWords(b.card_brand, b.card_last4)} (saved)` : 'none saved'}</span>
              {moneyCardLine(b) && (
                <span className="block text-amber-200" data-testid="consult-money-card">{moneyCardLine(b)}</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">Attendance</dt>
            <dd className="text-slate-100 break-words">
              <span data-testid="consult-attendance">{attendanceText(b.attendance)}</span>
              {participantLines(b.attendance).length > 0 && (
                <span className="block mt-1.5">
                  <span className="block text-slate-400">Who joined</span>
                  <ul className="mt-0.5 list-disc pl-5 space-y-0.5" data-testid="consult-participants">
                    {participantLines(b.attendance).map((line, i) => (
                      <li key={i} className="break-words">{line}</li>
                    ))}
                  </ul>
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">Automatic settlement</dt>
            <dd className="text-slate-100 break-words" data-testid="consult-settle-due">
              {summaryWaiting
                ? 'Waiting for the "confirm the outcome" email: nothing is charged automatically until it has gone out. You can decide it now with the actions below.'
                : b.settle_due_at
                  ? formatDate(b.settle_due_at)
                  : 'not scheduled'}
            </dd>
          </div>
          {b.meet_url && (
            <div className="md:col-span-2">
              <dt className="text-slate-400">Google Meet</dt>
              <dd>
                <a href={b.meet_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 break-all">
                  <Video className="w-4 h-4 shrink-0" /> {b.meet_url}
                </a>
              </dd>
            </div>
          )}
          <div className="md:col-span-2">
            <dt className="text-slate-400">What the call is about</dt>
            <dd className="text-slate-100 whitespace-pre-wrap break-words">{b.topic}</dd>
          </div>
          {b.consent && (
            <div className="md:col-span-2">
              <dt className="text-slate-400">Consent record</dt>
              <dd className="text-slate-300 text-xs font-mono break-all space-y-0.5">
                <div>terms {b.consent.terms_version ?? '?'} · sha256 {b.consent.terms_hash ?? '?'}</div>
                <div>{b.consent.at ? formatDate(b.consent.at) : ''} · IP {b.consent.ip ? b.consent.ip : 'not recorded'}</div>
                <div>{b.consent.user_agent ?? ''}</div>
              </dd>
            </div>
          )}
        </dl>
      </div>

      {/* ---- Attempts waiting to be checked in Stripe (W1b) ---- */}
      {(b.needs_review?.length ?? 0) > 0 && (
        <div className="bg-amber-950/30 border border-amber-500/40 rounded-2xl p-5 space-y-4" data-testid="consult-review">
          <div>
            <h3 className="text-sm font-semibold text-amber-100">Payment being checked: check in Stripe before anything else</h3>
            <p className="text-sm text-amber-100/90 mt-1">
              The outcome of {b.needs_review!.length === 1 ? 'this payment attempt is' : 'these payment attempts are'} unknown.
              This is not a refused card, and the client has not been told of a card problem.
              Look the payment up in Stripe, then record what you found. Charging again before that could take the money twice.
            </p>
          </div>
          <ul className="space-y-4">
            {b.needs_review!.map((r) => {
              const key = String(r.charge_id);
              const typed = reviewDollars[key] ?? String(r.amount_cents / 100);
              const typedCents = Math.round(Number(typed || '0') * 100);
              const isHold = r.kind === 'hold';
              const body = (extra: Record<string, unknown>) => ({ ...extra, charge_id: r.charge_id });
              return (
                <li key={key} className="rounded-xl border border-amber-500/30 bg-slate-950/50 p-4 space-y-3">
                  <p className="text-sm text-slate-100 break-words">
                    {isHold ? 'Card hold' : 'Charge'} for {REASON_LABEL[r.reason] ?? r.reason.replace(/_/g, ' ')}, {money(r.amount_cents)}, attempted {formatDate(r.created_at)}.
                  </p>
                  <div className="flex flex-wrap items-end gap-2">
                    <label className="block">
                      <span className={labelCls}>Amount you see in Stripe (USD)</span>
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={typed}
                        onChange={(e) => setReviewDollars({ ...reviewDollars, [key]: e.target.value })}
                        className={inputCls}
                        disabled={isHold || !A.can_review}
                        aria-label={`Amount paid in Stripe for attempt ${key}, in dollars`}
                      />
                    </label>
                    <button
                      type="button"
                      disabled={isHold || !A.can_review || typedCents < 1 || busy !== null}
                      className={`${actionBtn} bg-emerald-500/15 text-emerald-200 border-emerald-500/40 hover:bg-emerald-500/25`}
                      onClick={() =>
                        confirmThen(
                          `Record that Stripe shows ${money(typedCents)} paid by ${who} for ${REASON_LABEL[r.reason] ?? r.reason}? The site checks this with Stripe first; if confirmed, the booking is marked paid and the client is sent the receipt.`,
                          () => void act(`review-settled-${key}`, 'review-settled', body({ cents: typedCents }), (amt) => `Recorded as paid in Stripe: ${money(amt ?? typedCents)}.`),
                        )
                      }
                    >
                      <CheckCircle2 className="w-4 h-4" /> Paid in Stripe
                    </button>
                    <button
                      type="button"
                      disabled={!A.can_review || busy !== null}
                      className={`${actionBtn} bg-slate-800/60 text-slate-200 border-slate-600 hover:bg-slate-700/60`}
                      onClick={() =>
                        confirmThen(
                          `Record that Stripe shows nothing taken for this ${isHold ? 'card hold' : 'charge'} of ${money(r.amount_cents)} (${who})? The site checks this with Stripe first. Nothing is charged now; ${isHold ? 'a new hold can then be placed' : 'you can then press Charge again'}.`,
                          () => void act(`review-not-charged-${key}`, 'review-not-charged', body({}), () => `Recorded as not charged (${money(0)} taken).${isHold ? '' : ' Charge can be tried again.'}`),
                        )
                      }
                    >
                      <CircleSlash className="w-4 h-4" /> Not charged
                    </button>
                  </div>
                  {isHold && <p className="text-xs text-amber-200/90">A hold takes no money, so it cannot be marked as paid: if Stripe shows it captured, refund it there.</p>}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* ---- Actions ---- */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-5" data-testid="consult-actions">
        <h3 className="text-sm font-semibold text-white">Actions</h3>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className={labelCls}>Charge for</span>
                <select
                  value={chargeMinutes ?? b.minutes}
                  onChange={(e) => setChargeMinutes(Number(e.target.value))}
                  className={inputCls}
                  disabled={!A.can_charge}
                  aria-label="Minutes to charge"
                >
                  {minuteOptions.map((m) => (
                    <option key={m} value={m}>
                      {minutesText(m)}
                      {m === b.minutes ? ' (booked)' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={!A.can_charge || busy !== null}
                className={`${actionBtn} bg-emerald-500/15 text-emerald-200 border-emerald-500/40 hover:bg-emerald-500/25`}
                onClick={() =>
                  confirmThen(
                    `Charge ${who} ${money(chargeCents)} for ${minutesText(chargeMinutes ?? b.minutes)} to ${cardText(b)}?`,
                    () =>
                      void act(
                        'charge',
                        'charge',
                        chargeMinutes && chargeMinutes !== b.minutes ? { minutes: chargeMinutes } : {},
                        (amt) => `Charged ${money(amt ?? chargeCents)} to ${cardText(b)}.`,
                      ),
                  )
                }
              >
                <CreditCard className="w-4 h-4" /> Charge {money(chargeCents)}
              </button>
            </div>
            <p className="text-xs text-slate-400">The client joined: capture the booked amount, or a shorter length.</p>
            <Why show={!A.can_charge}>{settleWhy()}</Why>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={!A.can_no_show || busy !== null}
                className={`${actionBtn} bg-amber-500/15 text-amber-200 border-amber-500/40 hover:bg-amber-500/25`}
                onClick={() =>
                  confirmThen(
                    `Mark ${who} as a no-show and charge the ${feePct}% fee of ${money(b.fee_cents)} to ${cardText(b)}? The rest of the hold is released.`,
                    () => void act('no-show', 'no-show', {}, (amt) => `No-show fee of ${money(amt ?? b.fee_cents)} charged to ${cardText(b)}.`),
                  )
                }
              >
                <UserX className="w-4 h-4" /> No-show {feePct}% ({money(b.fee_cents)})
              </button>
              <button
                type="button"
                disabled={!A.can_waive || busy !== null}
                className={`${actionBtn} bg-slate-800/60 text-slate-200 border-slate-600 hover:bg-slate-700/60`}
                onClick={() =>
                  confirmThen(
                    `Do not charge ${who}: ${money(0)} is charged and the hold of ${money(b.total_cents)} is released?`,
                    () => void act('waive', 'waive', {}, () => 'Marked as not charged; any hold is released.'),
                  )
                }
              >
                <CircleSlash className="w-4 h-4" /> Do not charge ({money(0)})
              </button>
            </div>
            <p className="text-xs text-slate-400">The client did not join, or you choose to waive the call.</p>
            <Why show={!A.can_no_show && !A.can_waive}>{settleWhy()}</Why>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <label className="block flex-1 min-w-[12rem]">
                <span className={labelCls}>Note to the client (optional)</span>
                <input value={cancelNote} onChange={(e) => setCancelNote(e.target.value)} className={inputCls} disabled={!A.can_cancel} />
              </label>
              <button
                type="button"
                disabled={!A.can_cancel || busy !== null}
                className={`${actionBtn} bg-red-500/15 text-red-200 border-red-500/40 hover:bg-red-500/25`}
                onClick={() =>
                  confirmThen(
                    `Cancel the booking for ${who} at no charge (${money(0)})? The calendar event is removed, any hold is released and the client is emailed.`,
                    () =>
                      void act(
                        'cancel',
                        'cancel',
                        cancelNote.trim() ? { note: cancelNote.trim() } : {},
                        () => 'Booking cancelled at no charge.',
                      ),
                  )
                }
              >
                <XCircle className="w-4 h-4" /> Cancel ({money(0)})
              </button>
            </div>
            <p className="text-xs text-slate-400">You cancel: always free for the client.</p>
            <Why show={!A.can_cancel}>{cancelWhy}</Why>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className={labelCls}>Refund (USD, up to {money(refundable)})</span>
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  max={refundable / 100}
                  value={refundDollars}
                  onChange={(e) => setRefundDollars(e.target.value)}
                  className={inputCls}
                  disabled={!A.can_refund}
                  aria-label="Refund amount in dollars"
                />
              </label>
              <button
                type="button"
                disabled={!A.can_refund || refundCents <= 0 || refundCents > refundable || busy !== null}
                className={`${actionBtn} bg-violet-500/15 text-violet-200 border-violet-500/40 hover:bg-violet-500/25`}
                onClick={() =>
                  confirmThen(`Refund ${money(refundCents)} to ${who} on ${cardText(b)}?`, () =>
                    void act('refund', 'refund', { cents: refundCents }, (amt) => `Refunded ${money(amt ?? refundCents)} to ${cardText(b)}.`),
                  )
                }
              >
                <Undo2 className="w-4 h-4" /> Refund{refundCents > 0 ? ` ${money(refundCents)}` : ''}
              </button>
            </div>
            <p className="text-xs text-slate-400">
              {(b.disputed_cents ?? 0) > 0
                ? `${money(b.disputed_cents ?? 0)} is held by, or was lost to, a dispute at the client's bank and cannot be refunded from here${A.can_refund ? `; up to ${money(refundable)} can be.` : '.'}`
                : A.can_refund
                  ? 'Returns money already charged.'
                  : charged > 0
                    ? 'Everything charged has been refunded.'
                    : 'Nothing has been charged, so there is nothing to refund.'}
            </p>
          </div>
        </div>
      </div>

      {/* ---- Money ledger ---- */}
      {(b.charges?.length ?? 0) > 0 && (
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Payments with Stripe</h3>
          <ol className="space-y-3" data-testid="consult-ledger">
            {b.charges!.map((c) => (
              <li key={String(c.id)} className="grid grid-cols-1 sm:grid-cols-[12rem_1fr] gap-x-4 text-sm">
                <span className="text-slate-400 tabular-nums">{formatDate(c.created_at)}</span>
                <span className="text-slate-100 break-words">
                  <span className="font-semibold">{LEDGER_KIND[c.kind] ?? c.kind.replace(/_/g, ' ')}</span>
                  {c.reason ? ` for ${REASON_LABEL[c.reason] ?? c.reason.replace(/_/g, ' ')}` : ''}: {money(c.amount_cents)}
                  {' · '}
                  {c.status.replace(/_/g, ' ')}
                  {c.card_last4 ? ` · ${cardWords(c.card_brand, c.card_last4)}` : ''}
                  {c.error_message ? <span className="block text-slate-300">{c.error_message}</span> : null}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* ---- Timeline ---- */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Timeline</h3>
        {events.length === 0 ? (
          <p className="text-sm text-slate-400">No events recorded.</p>
        ) : (
          <ol className="space-y-3" data-testid="consult-timeline">
            {events.map((e, i) => (
              <li key={`${e.at}-${i}`} className="grid grid-cols-1 sm:grid-cols-[12rem_1fr] gap-x-4 text-sm">
                <span className="text-slate-400 tabular-nums">{formatDate(e.at)}</span>
                <span className="text-slate-100 break-words">
                  <span className="font-semibold">{(e.kind || e.type || 'event').replace(/_/g, ' ')}</span>
                  {e.detail || e.message ? `: ${e.detail || e.message}` : ''}
                  {typeof e.cents === 'number' ? ` (${money(e.cents)})` : ''}
                  {e.actor ? <span className="text-slate-400"> · {e.actor}</span> : null}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

// ----- Settings ---------------------------------------------------------------

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
function parseWindows(text: string): string[][] {
  return text
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => p.split(/\s*[-–]\s*/).map((t) => t.trim().padStart(5, '0')));
}
const ALL_DURATIONS = [30, 60, 90, 120, 150, 180];

type NumKey =
  | 'step_minutes'
  | 'buffer_minutes'
  | 'min_notice_hours'
  | 'horizon_days'
  | 'max_per_day'
  | 'standard_from_days'
  | 'fee_percent'
  | 'free_cancel_hours'
  | 'hold_lead_hours'
  | 'auto_settle_hours'
  | 'reminder_before_deadline_hours'
  | 'reminder_before_start_hours';

const NUM_FIELDS: { key: NumKey; label: string; min: number; max: number; help: string; choices?: number[] }[] = [
  { key: 'step_minutes', label: 'Start times every', min: 15, max: 60, help: 'Slot step: 15, 30 or 60 minutes.', choices: [15, 30, 60] },
  { key: 'buffer_minutes', label: 'Gap around busy time (min)', min: 0, max: 240, help: 'Kept free before and after anything busy.' },
  { key: 'min_notice_hours', label: 'Minimum notice (hours)', min: 0, max: 720, help: 'No booking closer than this to now.' },
  { key: 'horizon_days', label: 'Bookable ahead (days)', min: 1, max: 365, help: 'How far ahead clients can book.' },
  { key: 'max_per_day', label: 'Consults per day (max)', min: 0, max: 20, help: '0 = no limit.' },
  { key: 'standard_from_days', label: 'Standard rate from (days ahead)', min: 2, max: 60, help: 'Days ahead at which the standard rate starts.' },
  { key: 'fee_percent', label: 'No-show / late-cancel fee (%)', min: 0, max: 100, help: 'Share of the booked amount.' },
  { key: 'free_cancel_hours', label: 'Free cancellation until (hours before)', min: 0, max: 168, help: 'Later cancellations pay the fee.' },
  { key: 'hold_lead_hours', label: 'Card hold placed (hours before)', min: 1, max: 96, help: 'Authorization for the full amount; at most 96 h (a card authorization lapses after 5 to 7 days).' },
  { key: 'auto_settle_hours', label: 'Default outcome after (hours past end)', min: 0, max: 72, help: 'Unless you choose first. Hold lead + this: at most 120 h.' },
  { key: 'reminder_before_deadline_hours', label: 'First reminder (hours before free cancellation ends)', min: 1, max: 168, help: 'Sent while cancelling is still free. 24 h = two days before the start with 24 h free cancellation.' },
  { key: 'reminder_before_start_hours', label: 'Last reminder (hours before the start)', min: 1, max: 48, help: 'Shortly before the call.' },
];

function SettingsForm({ onAuthError, onSaved }: { onAuthError: () => void; onSaved: () => void }) {
  const [s, setS] = useState<ConsultSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [hours, setHours] = useState<Record<string, string>>({});
  const [nums, setNums] = useState<Record<NumKey, string>>({} as Record<NumKey, string>);
  const [rates, setRates] = useState<Record<Tier, string>>({} as Record<Tier, string>);
  const [durations, setDurations] = useState<number[]>([]);
  const [tz, setTz] = useState('');
  const [enabled, setEnabled] = useState(true);

  const adopt = (x: ConsultSettings) => {
    setS(x);
    setHours(Object.fromEntries(DAYS.map(([d]) => [d, windowsText(x.weekly_hours?.[d])])));
    setNums(Object.fromEntries(NUM_FIELDS.map((f) => [f.key, x[f.key] === undefined || x[f.key] === null ? '' : String(x[f.key])])) as Record<NumKey, string>);
    setRates(
      Object.fromEntries(
        TIERS.map((t) => {
          const c = x.rates_cents_per_hour?.[t.key];
          // 0 (or null) = never set (W1b: a fresh database has no rates).
          return [t.key, typeof c === 'number' && c > 0 ? String(c / 100) : ''];
        }),
      ) as Record<Tier, string>,
    );
    setDurations([...(x.durations ?? [])].sort((a, b) => a - b));
    setTz(x.timezone ?? '');
    setEnabled(Boolean(x.enabled));
  };

  const load = useCallback(async () => {
    try {
      adopt(await api<ConsultSettings>('/api/admin/consult/settings'));
      setError(null);
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setFlash(null);
    // Refuse to send a blank: an emptied field must never save as 0 (a free
    // call, a 0% fee, no notice).
    const blankNum = NUM_FIELDS.find((f) => nums[f.key]?.trim() === '');
    if (blankNum) {
      setError(`"${blankNum.label}" is empty. Enter a number.`);
      return;
    }
    const outOfRange = NUM_FIELDS.find((f) => {
      const v = Number(nums[f.key]);
      return !Number.isInteger(v) || v < f.min || v > f.max || (f.choices && !f.choices.includes(v));
    });
    if (outOfRange) {
      setError(
        outOfRange.choices
          ? `"${outOfRange.label}" must be ${outOfRange.choices.join(', ').replace(/, (\d+)$/, ' or $1')} minutes.`
          : `"${outOfRange.label}" must be a whole number from ${outOfRange.min} to ${outOfRange.max}.`,
      );
      return;
    }
    if (Number(nums.hold_lead_hours) + Number(nums.auto_settle_hours) > 120) {
      setError('The card hold (hours before) plus the default outcome (hours after) can be at most 120 hours: a card authorization lapses after five to seven days.');
      return;
    }
    // A rate never set may stay blank (sent back as 0, which the server keeps as
    // "not set"); a rate that is set can be changed but never emptied.
    const savedRate = (t: Tier) => {
      const c = s?.rates_cents_per_hour?.[t];
      return typeof c === 'number' && c > 0;
    };
    const blankRate = TIERS.find((t) => (rates[t.key]?.trim() ? !(Number(rates[t.key]) > 0) : savedRate(t.key)));
    if (blankRate) {
      setError(`Enter the ${blankRate.label} rate: a whole number of dollars per hour, more than zero.`);
      return;
    }
    if (enabled && TIERS.some((t) => !savedRate(t.key))) {
      setError('Booking cannot be switched on until all four hourly rates are saved. Save the rates first, then switch booking on.');
      return;
    }
    const centsRate = TIERS.find((t) => rates[t.key]?.trim() && !Number.isInteger(Number(rates[t.key])));
    if (centsRate) {
      setError(`The ${centsRate.label} rate must be whole dollars per hour (no cents).`);
      return;
    }
    if (durations.length === 0) {
      setError('Choose at least one call length.');
      return;
    }
    const payload: ConsultSettings = {
      enabled,
      timezone: tz.trim(),
      weekly_hours: Object.fromEntries(DAYS.map(([d]) => [d, parseWindows(hours[d] ?? '')])),
      durations,
      rates_cents_per_hour: Object.fromEntries(
        TIERS.map((t) => [t.key, rates[t.key]?.trim() ? Math.round(Number(rates[t.key]) * 100) : 0]),
      ) as Record<Tier, number>,
      ...(Object.fromEntries(NUM_FIELDS.map((f) => [f.key, Number(nums[f.key])])) as Record<NumKey, number>),
    };
    setSaving(true);
    try {
      adopt(await api<ConsultSettings>('/api/admin/consult/settings', { method: 'PUT', body: JSON.stringify(payload) }));
      setFlash('Consulting settings saved.');
      onSaved();
    } catch (err) {
      reportError(err, onAuthError, setError);
    } finally {
      setSaving(false);
    }
  }

  if (!s) {
    return error ? <Notice kind="error">{error}</Notice> : <p className="text-sm text-slate-400">Loading settings…</p>;
  }
  // Rates as last saved on the server (not as typed): 0 or null = never set.
  const unsetRates = TIERS.filter((t) => {
    const c = s.rates_cents_per_hour?.[t.key];
    return !(typeof c === 'number' && c > 0);
  });
  const canSwitchOn = unsetRates.length === 0;

  return (
    <form onSubmit={save} noValidate className="space-y-6 pb-24" data-testid="consult-settings">
      {error && <div role="alert"><Notice kind="error">{error}</Notice></div>}
      {flash && <div role="status"><Notice kind="success">{flash}</Notice></div>}

      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div className="flex flex-wrap items-start gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-labelledby="consult-enabled-label"
            aria-describedby="consult-enabled-help"
            disabled={!enabled && !canSwitchOn}
            onClick={() => setEnabled((v) => !v)}
            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60 ${
              enabled ? 'bg-cyan-500 border-cyan-400' : 'bg-slate-800 border-slate-600'
            }`}
            data-testid="consult-enabled-switch"
          >
            <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${enabled ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
          <div className="min-w-0">
            <div id="consult-enabled-label" className="text-sm font-semibold text-white">
              Booking is {enabled ? 'open' : 'closed'} on /consult
            </div>
            <p id="consult-enabled-help" className="text-xs text-slate-400 mt-0.5">
              {canSwitchOn
                ? 'Off: visitors see "temporarily unavailable" and a link to Contact. The change takes effect when you save.'
                : 'Save all four hourly rates first; then this switch can be turned on.'}
            </p>
          </div>
        </div>

        <div>
          <div className="text-xs uppercase tracking-wider text-slate-400 mb-2">
            Consulting hours on your clock — blank is a day off; several windows: 09:00-12:00, 13:00-18:00
          </div>
          <div className="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-1.5 items-center max-w-xl">
            {DAYS.map(([d, label]) => (
              <React.Fragment key={d}>
                <label htmlFor={`consult-hours-${d}`} className="text-sm text-slate-300">{label}</label>
                <input
                  id={`consult-hours-${d}`}
                  value={hours[d] ?? ''}
                  onChange={(e) => setHours({ ...hours, [d]: e.target.value })}
                  placeholder="day off"
                  className="w-full min-w-0 rounded-lg bg-slate-950 border border-slate-800 px-2 py-1 text-white text-sm font-mono"
                />
              </React.Fragment>
            ))}
          </div>
        </div>

        <label className="block max-w-xs">
          <span className={labelCls}>Time zone</span>
          <input value={tz} onChange={(e) => setTz(e.target.value)} className={inputCls} />
        </label>

        <fieldset>
          <legend className={labelCls}>Call lengths offered</legend>
          <div className="flex flex-wrap gap-3">
            {ALL_DURATIONS.map((d) => (
              <label key={d} className="inline-flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  className="accent-cyan-400"
                  checked={durations.includes(d)}
                  onChange={(e) =>
                    setDurations((cur) => (e.target.checked ? [...cur, d].sort((a, b) => a - b) : cur.filter((x) => x !== d)))
                  }
                />
                {minutesText(d)}
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-4">
        <h3 className="text-sm font-semibold text-white">Hourly rate by urgency (whole US dollars per hour, billed in 30-minute steps)</h3>
        {unsetRates.length > 0 && (
          <div role="status" data-testid="rates-unset">
            <Notice kind="warn">
              {unsetRates.length === TIERS.length ? 'No rates are set yet' : `Not set yet: ${unsetRates.map((t) => t.label).join(', ')}`}.
              Clients cannot book until all four rates are saved. Enter them below and press Save.
            </Notice>
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {TIERS.map((t) => (
            <label key={t.key} className="block">
              <span className={labelCls}>{t.label}</span>
              <input
                type="number"
                min={1}
                step="1"
                placeholder="not set"
                value={rates[t.key] ?? ''}
                onChange={(e) => setRates({ ...rates, [t.key]: e.target.value })}
                className={inputCls}
                aria-label={`${t.label} rate in US dollars per hour`}
              />
              <span className="text-[11px] text-slate-400 mt-1 block">{t.hint}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Rules</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {NUM_FIELDS.map((f) => (
            <label key={f.key} className="block">
              <span className={labelCls}>{f.label}</span>
              {f.choices ? (
                <select
                  value={nums[f.key] ?? ''}
                  onChange={(e) => setNums({ ...nums, [f.key]: e.target.value })}
                  className={inputCls}
                  aria-label={f.label}
                >
                  {!f.choices.map(String).includes(nums[f.key] ?? '') && <option value={nums[f.key] ?? ''}>{nums[f.key] || 'choose'}</option>}
                  {f.choices.map((c) => (
                    <option key={c} value={String(c)}>{c} minutes</option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  min={f.min}
                  max={f.max}
                  step={1}
                  value={nums[f.key] ?? ''}
                  onChange={(e) => setNums({ ...nums, [f.key]: e.target.value })}
                  className={inputCls}
                  aria-label={f.label}
                />
              )}
              <span className="text-[11px] text-slate-400 mt-1 block">{f.help}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn-primary text-sm py-2 px-4 disabled:opacity-50" disabled={saving}>
          {saving ? 'Saving…' : 'Save consulting settings'}
        </button>
        <button type="button" className="btn-secondary text-sm py-2 px-4" onClick={() => void load()} disabled={saving}>
          Discard changes
        </button>
      </div>
    </form>
  );
}

// ----- Page -------------------------------------------------------------------

export default function ConsultPage({
  view,
  go,
  onAuthError,
}: {
  view: Extract<ViewState, { page: 'consult' }>;
  go: (v: ViewState, opts?: { replace?: boolean }) => void;
  onAuthError: () => void;
}) {
  const [status, setStatus] = useState<ConsultStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [listKey, setListKey] = useState(0);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await api<ConsultStatus>('/api/admin/consult/status'));
      setStatusError(null);
    } catch (e) {
      reportError(e, onAuthError, setStatusError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const tab = view.booking ? 'bookings' : view.tab ?? 'bookings';
  const tabBtn = (key: 'bookings' | 'settings', label: string, Icon: typeof Settings) => (
    <button
      type="button"
      onClick={() => go(key === 'settings' ? { page: 'consult', tab: 'settings' } : { page: 'consult' }, { replace: true })}
      aria-current={tab === key ? 'page' : undefined}
      className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm border transition-colors ${
        tab === key
          ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'
          : 'text-slate-300 hover:text-white hover:bg-slate-800/60 border-transparent'
      }`}
    >
      <Icon className="w-4 h-4" /> {label}
    </button>
  );

  return (
    <Section
      icon={<CalendarClock className="w-5 h-5 text-cyan-400" />}
      title="Consulting"
      sub="Paid expert calls booked on /consult: open times, every booking with its attendance and payment, and the money actions."
      actions={<RefreshButton onClick={() => { void loadStatus(); setListKey((k) => k + 1); }} loading={loading} />}
    >
      <div className="space-y-6">
        {statusError && <Notice kind="error">{statusError}</Notice>}
        <StatusStrip s={status} openSettings={() => go({ page: 'consult', tab: 'settings' }, { replace: true })} />

        <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
          {tabBtn('bookings', 'Bookings', CalendarClock)}
          {tabBtn('settings', 'Settings', Settings)}
        </div>

        {view.booking ? (
          <BookingDetail
            key={view.booking}
            id={view.booking}
            onAuthError={onAuthError}
            back={() => go({ page: 'consult' })}
            onChanged={() => void loadStatus()}
          />
        ) : tab === 'settings' ? (
          <SettingsForm onAuthError={onAuthError} onSaved={() => void loadStatus()} />
        ) : (
          <BookingsList key={listKey} onAuthError={onAuthError} open={(id) => go({ page: 'consult', booking: id })} />
        )}
      </div>
    </Section>
  );
}
