import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  CalendarCheck,
  CalendarX,
  CheckCircle2,
  Clock,
  CreditCard,
  Loader2,
  Video,
} from 'lucide-react';
import { usePageMeta } from '../lib/meta';
import {
  consult,
  ConsultError,
  fmtDateTime,
  fmtMinutes,
  usd,
  visitorTimeZone,
  type BookingStatus,
  type BookingView,
} from '../lib/consultApi';

/* /consult/booking/:ref?t=token[&card=ok|cancelled]
 *
 * The client's own booking: where Stripe sends them back, and where the
 * "manage your booking" link in every email lands. Client-only (not
 * prerendered, noindex): it needs the token from the URL and shows amounts
 * that belong to this one booking. */

const STATUS_COPY: Record<BookingStatus, { label: string; tone: string }> = {
  pending_card: { label: 'Waiting for your card', tone: 'bg-amber-500/15 text-amber-200 border-amber-500/40' },
  confirmed: { label: 'Confirmed', tone: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/40' },
  cancelled: { label: 'Cancelled', tone: 'bg-slate-600/20 text-slate-200 border-slate-500/40' },
  completed: { label: 'Completed', tone: 'bg-cyan-500/15 text-cyan-200 border-cyan-500/40' },
  no_show: { label: 'Missed (no-show)', tone: 'bg-red-500/15 text-red-200 border-red-500/40' },
  expired: { label: 'Expired', tone: 'bg-slate-600/20 text-slate-200 border-slate-500/40' },
};

const Shell = ({ children }: { children: React.ReactNode }) => (
  <div className="relative pt-32 pb-24">
    <div className="hero-backdrop" />
    <div className="absolute inset-0 -z-10 bg-hero-radial" />
    <div className="container-site max-w-3xl">
      <span className="eyebrow">Your consultation</span>
      {children}
    </div>
  </div>
);

const Alert = ({ kind, children }: { kind: 'error' | 'success' | 'warn'; children: React.ReactNode }) => {
  const cls =
    kind === 'error'
      ? 'border-red-900/60 bg-red-950/40 text-red-200'
      : kind === 'success'
        ? 'border-emerald-900/60 bg-emerald-950/40 text-emerald-200'
        : 'border-amber-900/60 bg-amber-950/40 text-amber-200';
  const Icon = kind === 'success' ? CheckCircle2 : AlertTriangle;
  return (
    <div role={kind === 'success' ? 'status' : 'alert'} className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${cls}`}>
      <Icon className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
};

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="grid grid-cols-1 sm:grid-cols-[11rem_1fr] gap-x-4 gap-y-0.5 py-3 border-b border-slate-800/70 last:border-0">
    <dt className="text-sm text-slate-400">{label}</dt>
    <dd className="text-sm text-slate-100 break-words">{children}</dd>
  </div>
);

export default function ConsultBookingPage() {
  const { ref = '' } = useParams();
  const [params] = useSearchParams();
  const token = params.get('t') ?? '';
  const card = params.get('card');

  usePageMeta('Your consultation booking', 'Manage your consultation booking.', { noindex: true });

  const [tz, setTz] = useState('');
  const [b, setB] = useState<BookingView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [cardNote, setCardNote] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<'cancel' | 'card' | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [waitingForCard, setWaitingForCard] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => setTz(visitorTimeZone()), []);

  const load = useCallback(async () => {
    if (!token) return null;
    try {
      const v = await consult.booking(ref, token);
      setB(v);
      setLoadError(null);
      return v;
    } catch (e) {
      if (e instanceof ConsultError && (e.status === 403 || e.status === 404)) {
        setLoadError('We could not find this booking. Please open the link from your confirmation email again.');
      } else {
        setLoadError(e instanceof Error ? e.message : 'Could not load your booking.');
      }
      return null;
    }
  }, [ref, token]);

  // First load. Back from Stripe with card=ok the webhook may land a moment
  // after the browser does: poll briefly until the booking leaves pending_card.
  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    (async () => {
      const v = await load();
      if (cancelled || !v || card !== 'ok' || v.status !== 'pending_card') return;
      setWaitingForCard(true);
      let tries = 0;
      const tick = async () => {
        tries++;
        const next = await load();
        if (cancelled) return;
        if (next && next.status === 'pending_card' && tries < 15) {
          timer = window.setTimeout(() => void tick(), 2000);
        } else {
          setWaitingForCard(false);
        }
      };
      timer = window.setTimeout(() => void tick(), 2000);
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [load, card]);

  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);

  async function doCancel() {
    setBusy('cancel');
    setActionError(null);
    try {
      const v = await consult.cancel(ref, token);
      setB(v);
      setConfirming(false);
      setFlash(
        v.charged_cents
          ? `Your booking is cancelled. A late-cancellation fee of ${usd(v.charged_cents)} applies.`
          : 'Your booking is cancelled. You have not been charged.',
      );
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not cancel the booking.');
    } finally {
      setBusy(null);
    }
  }

  async function goToCard() {
    setBusy('card');
    setActionError(null);
    setCardNote(null);
    try {
      const r = await consult.card(ref, token);
      if (!/^https?:\/\//i.test(r.checkout_url || '')) throw new Error('The card page link is missing. Please contact us.');
      window.location.assign(r.checkout_url);
    } catch (e) {
      setBusy(null);
      if (e instanceof ConsultError && e.status === 409) {
        // e.g. a hold is already on the card for this call: the server's sentence, as it is,
        // and the page reloads so it stops offering a card change it will not accept.
        setCardNote(e.message);
        void load();
        return;
      }
      setActionError(e instanceof Error ? e.message : 'Could not open card entry.');
    }
  }

  if (!token) {
    return (
      <Shell>
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">This link is incomplete</h1>
        <p className="text-slate-300">
          Please open the booking link from your confirmation email again; it carries a private code that
          this address is missing.
        </p>
        <Link to="/consult" className="btn-secondary mt-6">Book a consultation</Link>
      </Shell>
    );
  }

  if (loadError && !b) {
    return (
      <Shell>
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">Booking not available</h1>
        <Alert kind="error">{loadError}</Alert>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/consult" className="btn-secondary">Book a consultation</Link>
          <Link to="/contact" className="btn-ghost">Contact us</Link>
        </div>
      </Shell>
    );
  }

  if (!b || !tz) {
    return (
      <Shell>
        <p className="mt-6 font-mono text-sm uppercase tracking-widest text-cyan-400 animate-pulse" role="status">
          Loading your booking…
        </p>
      </Shell>
    );
  }

  const st = STATUS_COPY[b.status] ?? { label: b.status, tone: 'bg-slate-700/30 text-slate-200 border-slate-600/40' };
  const upcoming = b.status === 'confirmed' || b.status === 'pending_card';
  const differentZone = Boolean(b.timezone && b.timezone !== tz);
  // "Your card was refused" only when the server says the CARD was refused.
  // A payment parked for the owner to check ('review') or owed with nothing
  // in flight ('open') is the site's to settle, never the client's card: the
  // server sends card_problem false for both; if a charge_state ever reaches
  // this view, those two values still never show a card problem.
  const parkedOrOpen = ['review', 'open'].includes(String((b as { charge_state?: unknown }).charge_state ?? ''));
  const cardRefused = b.card_problem === true && !parkedOrOpen;
  // card_brand / card_last4: the card the hold is on, or the money was taken
  // from, when there is one; otherwise the saved card (second review fixes, A).
  const card4 = b.card_last4 ? `${b.card_brand ? b.card_brand.toUpperCase() : 'Card'} ending ${b.card_last4}` : null;
  // A confirmed call whose card may not be replaced and was not refused: the
  // temporary hold for the call is on that card, so it is the card for the call.
  const holdOnCard = b.status === 'confirmed' && b.can_replace_card === false && !cardRefused;

  let headline: React.ReactNode;
  switch (b.status) {
    case 'pending_card':
      headline = 'Save a card to confirm your call';
      break;
    case 'confirmed':
      headline = <>Your call is <span className="text-gradient">confirmed</span></>;
      break;
    case 'cancelled':
      headline = 'This booking is cancelled';
      break;
    case 'completed':
      headline = 'Thank you for your call';
      break;
    case 'no_show':
      headline = 'This call was missed';
      break;
    case 'expired':
      headline = 'This booking expired';
      break;
    default:
      headline = 'Your booking';
  }

  // The cancellation rule that applies right now, with what it would cost.
  let cancelRule: React.ReactNode = null;
  if (b.status === 'confirmed' || b.status === 'pending_card') {
    if (!b.can_cancel) {
      cancelRule = 'This booking can no longer be cancelled online. Please contact us if you cannot attend.';
    } else if (b.cancel_fee_cents > 0) {
      cancelRule = (
        <>
          Cancelling now costs the late-cancellation fee of <strong className="text-white">{usd(b.cancel_fee_cents)}</strong>.
        </>
      );
    } else if (b.free_cancel_until) {
      cancelRule = <>Free cancellation until {fmtDateTime(b.free_cancel_until, tz)}. After that, cancelling costs {usd(b.fee_cents)}.</>;
    } else {
      // No free-cancellation window applies, yet cancelling right now costs nothing.
      cancelRule = 'You can cancel now at no charge.';
    }
  }

  return (
    <Shell>
      <h1 className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-3">{headline}</h1>
      <p className="mb-6">
        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${st.tone}`} data-testid="booking-status">
          {st.label}
        </span>
        <span className="ml-3 font-mono text-xs text-slate-400">Ref {b.ref}</span>
      </p>

      <div className="space-y-4 mb-6">
        {card === 'ok' && b.status === 'confirmed' && !flash && (
          <Alert kind="success">Your card is saved and your call is confirmed. The calendar invitation with the Google Meet link is on its way to your inbox.</Alert>
        )}
        {card === 'ok' && b.status === 'pending_card' && (
          <Alert kind="warn">
            {waitingForCard ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Confirming your card with Stripe…
              </span>
            ) : (
              'Your card has not been confirmed yet. Refresh this page in a minute, or save the card again below.'
            )}
          </Alert>
        )}
        {card === 'cancelled' && b.status === 'pending_card' && (
          <Alert kind="warn">You left card entry before finishing, so the call is not confirmed yet. The time is held for a short while: save a card now to keep it.</Alert>
        )}
        {cardRefused && (
          <Alert kind="error">
            <span data-testid="card-problem">
              Your card was refused{b.card_last4 ? ` (${(b.card_brand || 'card').toUpperCase()} ending ${b.card_last4})` : ''}, so
              {b.status === 'confirmed' ? ' the temporary hold for this call could not be placed.' : ' the amount due could not be collected.'}{' '}
              {b.can_replace_card ? 'Please save another card below.' : 'Please contact us to settle it.'}
              {b.status === 'confirmed' && ' If no card works, the booking is cancelled 2 hours before the start.'}
            </span>
          </Alert>
        )}
        {flash && <Alert kind="success">{flash}</Alert>}
        {actionError && <Alert kind="error">{actionError}</Alert>}
        {cardNote && (
          <Alert kind="warn">
            <span data-testid="card-refusal">{cardNote}</span>
          </Alert>
        )}
      </div>

      <div className="card p-6 sm:p-8">
        <dl>
          <Row label="When">
            <span className="font-semibold">{fmtDateTime(b.start, tz)}</span>
            {differentZone && <span className="block text-slate-400">{fmtDateTime(b.start, b.timezone)} (the zone you booked in)</span>}
          </Row>
          <Row label="Length">{fmtMinutes(b.minutes)}</Row>
          <Row label="Booking type">{b.tier_label}</Row>
          {b.meet_url && upcoming && (
            <Row label="Google Meet">
              <a href={b.meet_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 break-all">
                <Video className="w-4 h-4 shrink-0" aria-hidden="true" /> {b.meet_url}
              </a>
            </Row>
          )}
          <Row label="Total">
            {usd(b.total_cents)}{' '}
            <span className="text-slate-400">
              {b.status === 'completed' || b.status === 'no_show' || b.status === 'cancelled' || b.status === 'expired'
                ? ''
                : 'charged only after the meeting'}
            </span>
          </Row>
          {(b.status === 'confirmed' || b.status === 'pending_card') && (
            <Row label="No-show or late cancellation">{usd(b.fee_cents)}</Row>
          )}
          {b.charged_cents !== null && b.charged_cents !== undefined && (
            <Row label="Charged">{usd(b.charged_cents)}{card4 ? ` to your ${card4}` : ''}</Row>
          )}
          {card4 && b.charged_cents === null && <Row label={holdOnCard ? 'Card for this call' : 'Card on file'}>{card4}</Row>}
          {cancelRule && <Row label="Cancellation">{cancelRule}</Row>}
        </dl>
      </div>

      {/* ---- Actions ---- */}
      {b.status === 'pending_card' && b.can_replace_card !== false && (
        <div className="mt-6 flex flex-wrap gap-3">
          <button type="button" className="btn-primary disabled:opacity-60" disabled={busy !== null} onClick={() => void goToCard()}>
            {busy === 'card' ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <CreditCard className="w-4 h-4" aria-hidden="true" />}
            Continue to card entry
          </button>
        </div>
      )}

      {holdOnCard && (
        <p className="mt-6 text-sm text-slate-300 flex items-start gap-2" data-testid="hold-on-card">
          <CreditCard className="w-4 h-4 mt-0.5 shrink-0 text-cyan-400" aria-hidden="true" />
          <span>
            A temporary hold for this call is on your {card4 ?? 'card'}. To use a different card, reply to your
            confirmation email before the call.
          </span>
        </p>
      )}

      {b.status !== 'pending_card' && b.can_replace_card === true && (
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            className={`${cardRefused ? 'btn-primary' : 'btn-secondary'} disabled:opacity-60`}
            disabled={busy !== null}
            onClick={() => void goToCard()}
          >
            {busy === 'card' ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <CreditCard className="w-4 h-4" aria-hidden="true" />}
            {cardRefused ? 'Save another card' : 'Replace card'}
          </button>
        </div>
      )}

      {(b.status === 'confirmed' || b.status === 'pending_card') && b.can_cancel && (
        <div className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
          {!confirming ? (
            <button
              ref={cancelBtnRef}
              type="button"
              className="inline-flex items-center gap-2 text-sm font-semibold text-red-300 hover:text-red-200"
              onClick={() => setConfirming(true)}
            >
              <CalendarX className="w-4 h-4" aria-hidden="true" /> Cancel this booking
            </button>
          ) : (
            <div role="group" aria-labelledby="cancel-q">
              <p id="cancel-q" className="text-sm text-white font-semibold mb-1">Cancel this booking?</p>
              <p className="text-sm text-slate-300 mb-4">
                {b.cancel_fee_cents > 0
                  ? `Cancelling now costs ${usd(b.cancel_fee_cents)}, charged to your ${card4 ?? 'card'}. This cannot be undone.`
                  : 'Cancelling now is free. This cannot be undone.'}
              </p>
              <div className="flex flex-wrap gap-3">
                <button
                  ref={confirmRef}
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void doCancel()}
                  className="inline-flex items-center gap-2 rounded-lg bg-red-500/90 hover:bg-red-500 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
                >
                  {busy === 'cancel' && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                  {b.cancel_fee_cents > 0 ? `Yes, cancel and pay ${usd(b.cancel_fee_cents)}` : 'Yes, cancel at no charge'}
                </button>
                <button
                  type="button"
                  className="btn-secondary py-2.5 px-4 text-sm"
                  disabled={busy !== null}
                  onClick={() => {
                    setConfirming(false);
                    window.setTimeout(() => cancelBtnRef.current?.focus(), 0);
                  }}
                >
                  Keep my booking
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {(b.status === 'expired' || b.status === 'cancelled') && (
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/consult" className="btn-primary">
            <CalendarCheck className="w-4 h-4" aria-hidden="true" /> Book a new time
          </Link>
        </div>
      )}

      {b.status === 'expired' && (
        <p className="mt-4 text-sm text-slate-300">
          This booking could not be confirmed, and nothing was charged. A time is reserved for a short while
          after you choose it. That reservation ended before the booking was confirmed: it ran out, it was ended
          early because other people were booking at the same moment, or the time or the day filled up while
          the card was being entered. Please pick another time.
        </p>
      )}

      {(b.status === 'completed' || b.status === 'no_show') && (
        <p className="mt-6 text-sm text-slate-300 flex items-start gap-2">
          <Clock className="w-4 h-4 mt-0.5 shrink-0 text-slate-400" aria-hidden="true" />
          Questions about a charge? Reply to the receipt email and our support desk will answer.
        </p>
      )}

      <p className="mt-10 text-sm text-slate-400">
        Need help with this booking?{' '}
        <Link to="/contact" className="text-cyan-400 hover:text-cyan-300">Contact us</Link>.
        {' '}<Link to="/consult" className="text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1">
          Consulting page <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
        </Link>
      </p>
    </Shell>
  );
}
