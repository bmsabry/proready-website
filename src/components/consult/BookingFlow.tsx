import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  Check,
  Clock,
  CreditCard,
  Globe,
  Loader2,
  Lock,
} from 'lucide-react';
import {
  consult,
  ConsultError,
  fmtDateTime,
  fmtDay,
  fmtMinutes,
  fmtTime,
  tierLabel,
  timeZoneOptions,
  usd,
  type Availability,
  type Quote,
  type Slot,
} from '../../lib/consultApi';

/* The three-step booking flow on /consult.
 *
 *   1. pick a time   (visitor's zone; urgency as a label, never a price)
 *   2. pick a length  -> POST /quote: the first and only place a price shows
 *   3. your details + the full terms from the quote + consent -> POST /book,
 *      then off to Stripe to save a card (nothing is charged there).
 *
 * Availability is owned by the page (its hero shows "Next available" from
 * the same response) and handed in here with a reload function. */

export type AvailabilityState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: Availability }
  | { kind: 'unavailable'; reason: string };

const inputClass =
  'w-full bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-100 placeholder:text-slate-400 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/30 transition-colors';
const labelClass = 'block text-xs font-mono font-medium text-slate-300 uppercase tracking-widest mb-2';

const DAYS_SHOWN = 10;

type Step = 1 | 2 | 3;

const ErrorBox = ({ children, id }: { children: React.ReactNode; id?: string }) => (
  <div
    id={id}
    role="alert"
    className="flex items-start gap-3 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200"
  >
    <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
    <div className="min-w-0 break-words">{children}</div>
  </div>
);

export const UnavailableState = ({ reason }: { reason?: string }) => (
  <div className="text-center py-10 px-4" data-testid="consult-unavailable">
    <div className="mx-auto mb-4 w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 flex items-center justify-center">
      <CalendarClock className="w-6 h-6" aria-hidden="true" />
    </div>
    <h3 className="text-xl font-bold mb-2">Booking is temporarily unavailable</h3>
    <p className="text-slate-300 text-sm max-w-md mx-auto mb-6">
      {reason || 'Online booking is paused for the moment.'} You can still reach us directly and
      we will find a time with you.
    </p>
    <Link to="/contact" className="btn-primary">
      Contact us <ArrowRight className="w-4 h-4" aria-hidden="true" />
    </Link>
  </div>
);

const StepPill = ({ n, label, step }: { n: Step; label: string; step: Step }) => {
  const done = step > n;
  const here = step === n;
  return (
    <li className="flex items-center gap-2 min-w-0" aria-current={here ? 'step' : undefined}>
      <span
        className={`inline-flex items-center justify-center w-7 h-7 shrink-0 rounded-full text-xs font-bold border ${
          here
            ? 'bg-cyan-500 text-slate-950 border-cyan-400'
            : done
              ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40'
              : 'bg-slate-900 text-slate-400 border-slate-700'
        }`}
      >
        {done ? <Check className="w-3.5 h-3.5" aria-hidden="true" /> : n}
      </span>
      <span className={`text-xs sm:text-sm ${here ? 'text-white font-semibold' : 'text-slate-400'}`}>
        {label}
        {done && <span className="sr-only"> (done)</span>}
      </span>
    </li>
  );
};

export default function BookingFlow({
  state,
  tz,
  onTzChange,
  reload,
}: {
  state: AvailabilityState;
  tz: string;
  onTzChange: (tz: string) => void;
  reload: () => Promise<void>;
}) {
  const uid = useId();
  const [step, setStep] = useState<Step>(1);
  const [day, setDay] = useState<string | null>(null);
  const [showAllDays, setShowAllDays] = useState(false);
  const [slot, setSlot] = useState<Slot | null>(null);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({ full_name: '', email: '', company: '', phone: '', topic: '' });
  const [honeypot, setHoneypot] = useState('');
  const [agree, setAgree] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);
  const quoteSeq = useRef(0);

  const data = state.kind === 'ready' ? state.data : null;
  const days = useMemo(() => (data?.days ?? []).filter((d) => d.slots.length > 0), [data]);
  const zones = useMemo(() => (tz ? timeZoneOptions(tz) : []), [tz]);

  // Keep the chosen day valid as availability changes (reload, zone change).
  useEffect(() => {
    if (!days.length) {
      setDay(null);
      return;
    }
    if (!day || !days.some((d) => d.date === day)) setDay(days[0].date);
  }, [days, day]);

  // Move focus to the step heading when the step changes (not on first paint).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [step]);

  const durations = data?.durations?.length ? data.durations : [30, 60, 90, 120];
  const businessTz = data?.business_timezone || 'America/New_York';
  const differentZone = Boolean(tz && businessTz && tz !== businessTz);

  async function fetchQuote(s: Slot, m: number) {
    const seq = ++quoteSeq.current;
    setQuote(null);
    setQuoteError(null);
    setQuoteBusy(true);
    try {
      const q = await consult.quote(s.start, m);
      if (seq === quoteSeq.current) setQuote(q);
    } catch (e) {
      if (seq !== quoteSeq.current) return;
      if (e instanceof ConsultError && e.status === 409) {
        await slotTaken(e.message);
        return;
      }
      setQuoteError(e instanceof Error ? e.message : 'Could not get a price for this time.');
    } finally {
      if (seq === quoteSeq.current) setQuoteBusy(false);
    }
  }

  function chooseSlot(s: Slot) {
    setSlot(s);
    setNotice(null);
    const allowed = durations.filter((d) => d <= s.max_minutes);
    const initial = allowed.includes(60) ? 60 : allowed[allowed.length - 1] ?? null;
    setMinutes(initial);
    setStep(2);
    if (initial) void fetchQuote(s, initial);
    else {
      setQuote(null);
      setQuoteError('This time cannot fit a call. Please choose another time.');
    }
  }

  function chooseMinutes(m: number) {
    if (!slot || m === minutes) return;
    setMinutes(m);
    void fetchQuote(slot, m);
  }

  /** 409: the time is gone, or the price or terms changed since the quote.
   *  Say what the server said, then back to step 1 with fresh times. */
  async function slotTaken(detail?: string) {
    quoteSeq.current++;
    setQuote(null);
    setQuoteBusy(false);
    setSlot(null);
    setMinutes(null);
    setAgree(false);
    setStep(1);
    const said = (detail ?? '').trim();
    setNotice(
      `${said || 'That time is no longer available.'}${/[.!?]$/.test(said) || !said ? '' : '.'} The times below are up to date; please pick a time again.`,
    );
    await reload();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!slot || !minutes || !quote) return;
    setFormError(null);
    const name = form.full_name.trim();
    const email = form.email.trim();
    const topic = form.topic.trim();
    const missing: string[] = [];
    if (!name) missing.push('your name');
    if (!email) missing.push('your email');
    if (!topic) missing.push('what the call is about');
    if (missing.length) {
      setFormError(`Please enter ${missing.join(', ').replace(/, ([^,]*)$/, ' and $1')}.`);
      return;
    }
    if (!/^[^\s@]+@[^\s@]+$/.test(email)) {
      setFormError('Please enter a complete email address, for example name@company.com.');
      return;
    }
    if (!agree) {
      setFormError('Please confirm that you have read and agree to the booking terms.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await consult.book({
        start: slot.start,
        minutes,
        full_name: name,
        email,
        company: form.company.trim() || undefined,
        phone: form.phone.trim() || undefined,
        topic,
        timezone: tz,
        terms_version: quote.terms_version,
        agree: true,
        website: honeypot,
      });
      if (!/^https?:\/\//i.test(res.checkout_url || '')) {
        throw new ConsultError(500, 'The booking was created but the card page link is missing. Please contact us.');
      }
      window.location.assign(res.checkout_url);
      // Stay in the submitting state while the browser leaves the page.
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ConsultError && err.status === 409) {
        await slotTaken(err.message);
        return;
      }
      if (err instanceof ConsultError && err.status === 429) {
        // This visitor already has unfinished bookings (per address or per email),
        // or too many tries in an hour. The server's sentence says what to do; the
        // chosen time, length, details and consent stay filled in. No promise that
        // pressing again now will work: it may not, until the server's condition passes.
        const said = err.message.trim();
        setFormError(`${said}${/[.!?]$/.test(said) ? '' : '.'} The time and details you chose stay filled in below.`);
        return;
      }
      setFormError(err instanceof Error ? err.message : 'Could not create the booking. Please try again.');
    }
  }

  // ---------------------------------------------------------------- states

  if (state.kind === 'loading' || !tz) {
    return (
      <div className="py-16 text-center" role="status">
        <Loader2 className="w-7 h-7 mx-auto text-cyan-400 animate-spin" aria-hidden="true" />
        <p className="mt-3 text-sm text-slate-300">Loading open times…</p>
      </div>
    );
  }
  if (state.kind === 'unavailable') return <UnavailableState reason={state.reason} />;
  if (!data) return null;

  const tzPicker = (
    <label className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
      <Globe className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
      <span>Times shown in</span>
      <select
        value={tz}
        onChange={(e) => onTzChange(e.target.value)}
        className="max-w-full bg-slate-900/60 border border-slate-700 rounded-lg px-2 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-400"
        aria-label="Time zone for the times shown"
      >
        {zones.map((z) => (
          <option key={z} value={z}>
            {z.replace(/_/g, ' ')}
          </option>
        ))}
      </select>
    </label>
  );

  const selectedSummary = slot && (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm">
      <div className="text-white font-semibold break-words">{fmtDateTime(slot.start, tz)}</div>
      {differentZone && (
        <div className="text-slate-400 mt-0.5 break-words">
          {fmtDateTime(slot.start, businessTz)} for the expert
        </div>
      )}
      <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-mono uppercase tracking-wider text-cyan-300">
        <Clock className="w-3.5 h-3.5" aria-hidden="true" /> {tierLabel(slot.tier)} booking
      </div>
    </div>
  );

  // ---------------------------------------------------------------- step 1

  let body: React.ReactNode;
  if (step === 1) {
    const current = days.find((d) => d.date === day) ?? null;
    const shownDays = showAllDays ? days : days.slice(0, DAYS_SHOWN);
    const mixedTiers = current ? new Set(current.slots.map((s) => s.tier)).size > 1 : false;
    body = (
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          {tzPicker}
        </div>
        <p className="text-sm text-slate-400 -mt-3">
          The expert works on {(businessTz.split('/').pop() || businessTz).replace(/_/g, ' ')} time ({businessTz}).
          {differentZone ? ' Every time below is converted to the zone you chose.' : ''}
        </p>

        {days.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-6 text-center">
            <p className="text-white font-semibold">No open times right now</p>
            <p className="text-sm text-slate-300 mt-1">
              Every bookable time is taken at the moment.{' '}
              <Link to="/contact" className="text-cyan-400 hover:text-cyan-300 underline">
                Contact us
              </Link>{' '}
              and we will find one with you.
            </p>
          </div>
        ) : (
          <>
            <fieldset>
              <legend className={labelClass}>Day</legend>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
                {shownDays.map((d) => {
                  const active = d.date === day;
                  return (
                    <button
                      key={d.date}
                      type="button"
                      onClick={() => setDay(d.date)}
                      aria-pressed={active}
                      className={`rounded-xl border px-3 py-2.5 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60 ${
                        active
                          ? 'border-cyan-400 bg-cyan-500/15 text-white'
                          : 'border-slate-800 bg-slate-950/60 text-slate-200 hover:border-slate-600'
                      }`}
                    >
                      <span className="block text-sm font-semibold">{fmtDay(d.date, 'short')}</span>
                      <span className="block text-xs text-slate-400 mt-0.5">
                        {d.slots.length} time{d.slots.length === 1 ? '' : 's'} · {tierLabel(d.slots[0].tier)}
                      </span>
                    </button>
                  );
                })}
              </div>
              {days.length > DAYS_SHOWN && (
                <button
                  type="button"
                  onClick={() => setShowAllDays((v) => !v)}
                  className="btn-ghost mt-3"
                  aria-expanded={showAllDays}
                >
                  {showAllDays ? 'Show fewer days' : `Show all ${days.length} days`}
                </button>
              )}
            </fieldset>

            {current && (
              <fieldset>
                <legend className={labelClass}>Start time on {fmtDay(current.date)}</legend>
                <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
                  {current.slots.map((s) => (
                    <button
                      key={s.start}
                      type="button"
                      onClick={() => chooseSlot(s)}
                      className="rounded-lg border border-slate-800 bg-slate-950/60 px-2 py-2.5 text-sm font-semibold text-slate-100 hover:border-cyan-400 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60"
                      aria-label={`${fmtDateTime(s.start, tz)}, ${tierLabel(s.tier)} booking`}
                    >
                      {fmtTime(s.start, tz)}
                      {mixedTiers && (
                        <span className="block text-[11px] font-normal text-slate-400">{tierLabel(s.tier)}</span>
                      )}
                    </button>
                  ))}
                </div>
                <p className="mt-3 text-xs text-slate-400">
                  The rate depends on how soon the call is. You see it for the time you pick before you
                  enter any details.
                </p>
              </fieldset>
            )}
          </>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------- step 2

  if (step === 2 && slot) {
    const holdSoon = quote ? new Date(quote.hold_at).getTime() - Date.now() < 5 * 60_000 : false;
    body = (
      <div className="space-y-6">
        {selectedSummary}
        <fieldset>
          <legend className={labelClass}>Length of the call</legend>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2" role="radiogroup" aria-label="Length of the call">
            {durations.map((d) => {
              const allowed = d <= slot.max_minutes;
              const active = d === minutes;
              return (
                <button
                  key={d}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={!allowed || quoteBusy}
                  onClick={() => chooseMinutes(d)}
                  className={`rounded-xl border px-3 py-3 text-sm font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60 disabled:cursor-not-allowed ${
                    active
                      ? 'border-cyan-400 bg-cyan-500/15 text-white'
                      : allowed
                        ? 'border-slate-800 bg-slate-950/60 text-slate-200 hover:border-slate-600'
                        : 'border-slate-800/60 bg-slate-950/30 text-slate-500 line-through'
                  }`}
                >
                  {fmtMinutes(d)}
                  {!allowed && <span className="sr-only"> (not available at this time)</span>}
                </button>
              );
            })}
          </div>
          {durations.some((d) => d > slot.max_minutes) && (
            <p className="mt-2 text-xs text-slate-400">
              Up to {fmtMinutes(slot.max_minutes)} is free at this start time.
            </p>
          )}
        </fieldset>

        <div aria-live="polite">
          {quoteBusy && (
            <div className="flex items-center gap-2 text-sm text-slate-300 py-4" role="status">
              <Loader2 className="w-4 h-4 animate-spin text-cyan-400" aria-hidden="true" /> Getting the price for this time…
            </div>
          )}
          {quoteError && <ErrorBox>{quoteError}</ErrorBox>}
          {quote && !quoteBusy && (
            <div className="rounded-2xl border border-cyan-500/30 bg-cyan-500/5 p-5" data-testid="consult-quote">
              <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
                <span className="eyebrow">{quote.tier_label}</span>
                <span className="text-sm text-slate-300">
                  {usd(quote.rate_cents_per_hour)} per hour, billed in 30-minute steps
                </span>
              </div>
              <div className="flex flex-wrap items-end justify-between gap-2 border-b border-slate-800 pb-4 mb-4">
                <div>
                  <div className="text-xs font-mono uppercase tracking-widest text-slate-400">Total for {fmtMinutes(quote.minutes)}</div>
                  <div className="text-3xl font-bold text-white mt-1 tabular-nums">{usd(quote.total_cents)}</div>
                </div>
                <div className="text-sm text-emerald-300 font-medium">Charged only after the meeting</div>
              </div>
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
                <div>
                  <dt className="text-slate-400">Temporary hold on your card</dt>
                  <dd className="text-slate-100 break-words">
                    {usd(quote.total_cents)}{' '}
                    {holdSoon ? 'right after you save your card' : `on ${fmtDateTime(quote.hold_at, tz)}`}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-400">Free cancellation</dt>
                  <dd className="text-slate-100 break-words">
                    {quote.free_cancel_until
                      ? `Until ${fmtDateTime(quote.free_cancel_until, tz)}`
                      : 'Not available for this time'}
                  </dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-slate-400">No-show or late cancellation</dt>
                  <dd className="text-slate-100">
                    {quote.fee_percent}% of the booked amount: {usd(quote.fee_cents)}
                  </dd>
                </div>
              </dl>
            </div>
          )}
        </div>

        <div className="flex flex-col-reverse sm:flex-row sm:justify-between gap-3">
          <button type="button" className="btn-secondary" onClick={() => { quoteSeq.current++; setQuoteBusy(false); setStep(1); }}>
            <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Change time
          </button>
          <button
            type="button"
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0"
            disabled={!quote || quoteBusy}
            onClick={() => setStep(3)}
          >
            Continue <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- step 3

  if (step === 3 && slot && quote) {
    const field = (k: keyof typeof form) => ({
      id: `${uid}-${k}`,
      name: k,
      value: form[k],
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setForm({ ...form, [k]: e.target.value }),
      className: inputClass,
    });
    body = (
      <form onSubmit={submit} noValidate className="space-y-6" aria-describedby={formError ? `${uid}-err` : undefined}>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm flex flex-wrap items-center justify-between gap-2">
          <span className="text-white font-semibold break-words">
            {fmtDateTime(slot.start, tz)} · {fmtMinutes(quote.minutes)}
          </span>
          <span className="text-slate-200 tabular-nums">
            {quote.tier_label} · {usd(quote.total_cents)}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div>
            <label htmlFor={`${uid}-full_name`} className={labelClass}>
              Full name <span className="text-cyan-400" aria-hidden="true">*</span>
            </label>
            <input {...field('full_name')} autoComplete="name" required aria-required="true" maxLength={200} />
          </div>
          <div>
            <label htmlFor={`${uid}-email`} className={labelClass}>
              Email <span className="text-cyan-400" aria-hidden="true">*</span>
            </label>
            <input {...field('email')} type="email" autoComplete="email" required aria-required="true" maxLength={254} />
          </div>
          <div>
            <label htmlFor={`${uid}-company`} className={labelClass}>Company (optional)</label>
            <input {...field('company')} autoComplete="organization" maxLength={200} />
          </div>
          <div>
            <label htmlFor={`${uid}-phone`} className={labelClass}>Phone (optional)</label>
            <input {...field('phone')} type="tel" autoComplete="tel" maxLength={40} />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor={`${uid}-topic`} className={labelClass}>
              What the call is about <span className="text-cyan-400" aria-hidden="true">*</span>
            </label>
            <textarea
              {...field('topic')}
              rows={4}
              required
              aria-required="true"
              maxLength={4000}
              aria-describedby={`${uid}-topic-hint`}
              placeholder="The unit or system, what it is doing, what you have tried, and the decision you need to make."
            />
            <p id={`${uid}-topic-hint`} className="mt-1.5 text-xs text-slate-400">
              Do not include third-party proprietary or export-controlled information.
            </p>
          </div>
        </div>

        {/* Honeypot: invisible to people, irresistible to form bots. */}
        <div aria-hidden="true" className="absolute -left-[10000px] w-px h-px overflow-hidden">
          <label>
            Website
            <input
              type="text"
              name="website"
              tabIndex={-1}
              autoComplete="off"
              value={honeypot}
              onChange={(e) => setHoneypot(e.target.value)}
            />
          </label>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
          <h4 className="text-sm font-semibold text-white mb-3">Booking terms</h4>
          <ul className="space-y-2 text-sm text-slate-300 list-disc pl-5" data-testid="consult-terms">
            {quote.terms.map((t, i) => (
              <li key={i} className="break-words">{t}</li>
            ))}
          </ul>
          <label className="mt-5 flex items-start gap-3 text-sm text-slate-100 cursor-pointer">
            <input
              type="checkbox"
              name="agree"
              checked={agree}
              onChange={(e) => setAgree(e.target.checked)}
              className="mt-0.5 w-4 h-4 accent-cyan-400 shrink-0"
              required
              aria-required="true"
            />
            <span>
              I have read and agree to these terms, including the {quote.fee_percent}% fee for a no-show or
              a late cancellation.
            </span>
          </label>
        </div>

        {formError && <ErrorBox id={`${uid}-err`}>{formError}</ErrorBox>}

        <div className="flex flex-col-reverse sm:flex-row sm:justify-between sm:items-center gap-3">
          <button type="button" className="btn-secondary" onClick={() => setStep(2)} disabled={submitting}>
            <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Back
          </button>
          <button
            type="submit"
            className="btn-primary disabled:opacity-60 disabled:cursor-wait disabled:hover:translate-y-0"
            disabled={submitting}
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Opening secure card entry…
              </>
            ) : (
              <>
                <CreditCard className="w-4 h-4" aria-hidden="true" /> Save a card and confirm
              </>
            )}
          </button>
        </div>
        <p className="flex items-start gap-2 text-xs text-slate-400">
          <Lock className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
          Card details are entered on Stripe's secure page, never on this site. Saving a card charges
          nothing.
        </p>
      </form>
    );
  }

  const titles: Record<Step, string> = {
    1: 'Pick a time',
    2: 'Choose the length and see the price',
    3: 'Your details',
  };

  return (
    <div>
      <ol className="flex flex-wrap items-center gap-x-5 gap-y-2 mb-6" aria-label="Booking steps">
        <StepPill n={1} label="Time" step={step} />
        <StepPill n={2} label="Length and price" step={step} />
        <StepPill n={3} label="Details and card" step={step} />
      </ol>
      <h3 ref={headingRef} tabIndex={-1} className="text-2xl font-bold mb-5 focus:outline-none">
        {titles[step]}
      </h3>
      {notice && step === 1 && (
        <div className="mb-5">
          <ErrorBox>{notice}</ErrorBox>
        </div>
      )}
      {body}
    </div>
  );
}
