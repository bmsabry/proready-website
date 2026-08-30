import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Calendar,
  Users,
  Clock,
  Award,
  Flame,
  Gauge,
  Wrench,
  CheckCircle2,
  Lock,
  MessageSquare,
  Send,
  AlertTriangle,
  Layers,
  Fan,
  Cog,
  Cpu,
  FlaskConical,
  PlayCircle,
  Infinity as InfinityIcon,
} from 'lucide-react';
import { Reveal } from '../../components/ui';
import PayPalButtons, { fetchPaymentsConfig, PaymentsConfig } from '../../components/PayPalButtons';
import { usePageMeta } from '../../lib/meta';
import {
  formatIsoDate as formatStartDate,
  snapshotDayLabels,
  snapshotStartLabel,
} from '../../data/courseSnapshot';
import { MODULES, COURSE_SUBTITLE } from './microGasTurbineCurriculum';

// -----------------------------------------------------------------------------
// Course constants
// -----------------------------------------------------------------------------
// Course code matches the backend Course.code. Start date + seats are fetched
// from /api/courses/{code}; the constants below are fallbacks for local
// preview before the backend is reachable.
const COURSE_CODE = 'micro-gas-turbine-design-2026-10';
const DEFAULT_CAPACITY = 15;
// The live seat price. Fetched from the course record at runtime; this default
// keeps the prerendered HTML honest until that fetch lands.
const DEFAULT_PRICE_CENTS = 300000;
// The recorded on-demand edition this cohort includes (and cross-sells).
const RECORDED_PRODUCT_CODE = 'micro-gas-turbine-design';
const DEFAULT_RECORDED_PRICE_CENTS = 99900;
// Prerender fallback for the cohort start, taken from the build-time snapshot
// of the live course record (see data/courseSnapshot). The literal is only a
// last resort for a course the build has never been able to reach.
const DEFAULT_COHORT_DATE = snapshotStartLabel(COURSE_CODE, 'October 1, 2026');

// Backend endpoints. Set VITE_API_BASE in your deploy env to the Render URL.
// When unset (local dev without backend), the form simulates success so the UI
// can be previewed without the API running.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';
const COURSE_ENDPOINT = API_BASE ? `${API_BASE}/api/courses/${COURSE_CODE}` : '';
const REGISTER_ENDPOINT = API_BASE ? `${API_BASE}/api/register` : '';
const RECORDED_CATALOG_ENDPOINT = API_BASE
  ? `${API_BASE}/api/academy/catalog/${RECORDED_PRODUCT_CODE}`
  : '';

// 300000 + 'usd' -> "$3,000"; keeps cents only when they exist.
const formatAmount = (cents: number, currency: string): string =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: (currency || 'usd').toUpperCase(),
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);

// JSON-LD Course schema for search engines.
const COURSE_JSONLD = JSON.stringify({
  '@context': 'https://schema.org',
  '@type': 'Course',
  name: 'Micro Gas Turbine Design — Live Online Cohort',
  description:
    'Seven-day live online cohort on designing a 700 N single-shaft turbojet end to end: engine architecture and materials, centrifugal compressor aerodynamics, the evaporative tube combustor, the axial turbine, compressor maps and surge margin, turbomachinery CFD, and combustor design analysis. Four live hours per day over consecutive business days, with lifetime access to the complete recorded course included.',
  provider: {
    '@type': 'Organization',
    name: 'ProReadyEngineer LLC',
    url: 'https://proreadyengineer.com',
  },
});

// Curriculum content. Index 0 -> Day 1, index 1 -> Day 2, etc.
// Dates are *not* stored here — they come from the live API (day_dates)
// so the admin can adjust them without a code change.
//
// The seven live days map one-to-one onto the seven modules of the recorded
// programme (microGasTurbineCurriculum.ts), which is the single source of
// truth for titles, topics and objectives. A buyer comparing this agenda with
// the on-demand edition should find no gap — each live day teaches one module.
type Day = {
  title: string;
  chapters: string;
  summary: string;
  topics: string[];
  outcomes: string[];
  icon: React.ReactNode;
};

const DAY_ICONS: React.ReactNode[] = [
  <Layers className="w-6 h-6" />,
  <Fan className="w-6 h-6" />,
  <Flame className="w-6 h-6" />,
  <Cog className="w-6 h-6" />,
  <Gauge className="w-6 h-6" />,
  <Cpu className="w-6 h-6" />,
  <FlaskConical className="w-6 h-6" />,
];

const CURRICULUM: Day[] = MODULES.map((m, i) => ({
  title: m.title,
  chapters: `Module ${m.code} · ${m.topics.length} topics`,
  summary: m.summary,
  topics: m.topics,
  outcomes: m.objectives,
  icon: DAY_ICONS[i] ?? <Calendar className="w-6 h-6" />,
}));

// Placeholder rendered for days that exist in the admin schedule but go
// beyond the locally-defined curriculum content. Lets admins extend a
// course past the written agenda without immediately needing a code change.
const TBD_DAY: Day = {
  title: 'Schedule TBD',
  chapters: '',
  summary: 'Detailed agenda for this day will be published soon.',
  topics: ['Topic outline pending'],
  outcomes: [],
  icon: <Calendar className="w-6 h-6" />,
};

const IDEAL_FOR = [
  'Propulsion & Turbomachinery Engineers',
  'UAV / Small-Turbojet Developers',
  'Combustion & Test Engineers',
  'Graduate Engineers & Researchers',
  'Gas Turbine Enthusiasts',
];

// -----------------------------------------------------------------------------
// Page component
// -----------------------------------------------------------------------------
// Default schedule used when the API hasn't responded yet (or is unavailable
// in local preview). Admin can override these any time via the dashboard.
// Taken from the build-time snapshot of the live course record: the admin moves
// the dates in the dashboard and the next deploy picks them up, so there is
// nothing here to forget to update. The literals are a last resort only, for a
// course code the build has never once been able to reach.
const DEFAULT_DAY_DATES: string[] = snapshotDayLabels(COURSE_CODE, [
  'October 1, 2026',
  'October 2, 2026',
  'October 5, 2026',
  'October 6, 2026',
  'October 7, 2026',
  'October 8, 2026',
  'October 9, 2026',
]);

const MicroGasTurbineDesignLive = () => {
  usePageMeta(
    'Micro Gas Turbine Design — Live Online Cohort',
    'Seven-day live online cohort, four hours per day over consecutive business days, on designing a 700 N single-shaft turbojet end to end: architecture, centrifugal compressor, evaporative combustor, axial turbine, compressor maps, CFD and combustor analysis. Includes lifetime access to the complete recorded course.',
    {
      image: 'https://proreadyengineer.com/Micro_Gas_Turbine_Design_Infographic.jpg',
      jsonLd: {
        '@context': 'https://schema.org',
        '@type': 'Course',
        name: 'Micro Gas Turbine Design — Live Online Cohort',
        image: 'https://proreadyengineer.com/Micro_Gas_Turbine_Design_Infographic.jpg',
        description: COURSE_SUBTITLE,
        provider: { '@id': 'https://proreadyengineer.com/#org' },
        teaches: MODULES.map((m) => m.title),
        hasCourseInstance: [
          {
            '@type': 'CourseInstance',
            courseMode: 'Online',
            courseWorkload: 'P7D',
            instructor: {
              '@type': 'Person',
              name: 'Dr. Bassam Abdelnabi',
              jobTitle: 'Principal Consultant, Gas Turbine Combustion Expert',
            },
          },
        ],
        offers: { '@type': 'Offer', category: 'Paid' },
      },
    },
  );

  const [seatsTaken, setSeatsTaken] = useState<number | null>(null);
  const [capacity, setCapacity] = useState<number>(DEFAULT_CAPACITY);
  const [cohortDate, setCohortDate] = useState<string>(DEFAULT_COHORT_DATE);
  const [courseStatus, setCourseStatus] = useState<'open' | 'closed'>('open');
  const [seatsLoading, setSeatsLoading] = useState(true);
  // Per-day dates (formatted "October 1, 2026"). Defaults to the snapshot
  // schedule above; replaced by the API list when day_dates is non-empty.
  const [dayDates, setDayDates] = useState<string[]>(DEFAULT_DAY_DATES);
  const [formState, setFormState] = useState<'idle' | 'loading' | 'success' | 'duplicate' | 'error'>(
    'idle',
  );
  const [formError, setFormError] = useState<string | null>(null);
  // Online payment for the held seat. registrationId only exists after a real
  // (non-simulated) /api/register success; priceCents comes from the course
  // record. Unlike the invoice-only default elsewhere, this cohort has a
  // public per-seat price, so the fallback is the real price rather than 0.
  const [priceCents, setPriceCents] = useState<number>(DEFAULT_PRICE_CENTS);
  const [currency, setCurrency] = useState<string>('usd');
  // The recorded edition's price, shown in the pricing section so the
  // self-paced cross-link never quotes a stale number.
  const [recordedPriceCents, setRecordedPriceCents] = useState<number>(
    DEFAULT_RECORDED_PRICE_CENTS,
  );
  const [registrationId, setRegistrationId] = useState<number | null>(null);
  const [payCfg, setPayCfg] = useState<PaymentsConfig | null>(null);
  const [paidNow, setPaidNow] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const [cardLoading, setCardLoading] = useState(false);
  // Stripe Checkout returns to this page with ?paid=1 / ?cancelled=1.
  const [returnBanner, setReturnBanner] = useState<'paid' | 'cancelled' | null>(null);

  // Fetch live course data (start_date + seats + price). Falls back to the
  // constants when API_BASE is empty (local preview) or the request fails.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!COURSE_ENDPOINT) {
        if (!cancelled) {
          setSeatsTaken(0);
          setSeatsLoading(false);
        }
        return;
      }
      try {
        const res = await fetch(COURSE_ENDPOINT, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as {
          start_date: string;
          total_seats: number;
          seats_taken: number;
          status: 'open' | 'closed';
          day_dates?: string[];
          price_cents?: number;
          currency?: string;
        };
        if (!cancelled) {
          setSeatsTaken(data.seats_taken);
          setCapacity(data.total_seats);
          setCourseStatus(data.status);
          if (typeof data.price_cents === 'number' && data.price_cents > 0) {
            setPriceCents(data.price_cents);
            setCurrency(data.currency || 'usd');
          }
          // day_dates is the source of truth for cohort start/length when present.
          // Fall back to start_date only if day_dates is missing or empty.
          if (Array.isArray(data.day_dates) && data.day_dates.length > 0) {
            setDayDates(data.day_dates.map(formatStartDate));
            setCohortDate(formatStartDate(data.day_dates[0]));
          } else {
            setCohortDate(formatStartDate(data.start_date));
          }
          setSeatsLoading(false);
        }
      } catch {
        if (!cancelled) {
          setSeatsTaken(0);
          setSeatsLoading(false);
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // The recorded edition's live price, for the self-paced cross-link.
  useEffect(() => {
    if (!RECORDED_CATALOG_ENDPOINT) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(RECORDED_CATALOG_ENDPOINT);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && typeof data.price_cents === 'number' && data.price_cents > 0) {
          setRecordedPriceCents(data.price_cents);
        }
      } catch {
        /* keep the compiled-in default */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Stripe Checkout sends the buyer back with ?paid=1 or ?cancelled=1. Show
  // the matching banner at the register section and bring it into view.
  // (Runs only in the browser — the prerendered HTML carries no banner.)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const banner = params.get('paid') === '1' ? 'paid' : params.get('cancelled') === '1' ? 'cancelled' : null;
    if (!banner) return;
    setReturnBanner(banner);
    const t = window.setTimeout(() => {
      document.getElementById('register')?.scrollIntoView({ block: 'start' });
    }, 80);
    return () => window.clearTimeout(t);
  }, []);

  // Which providers may be offered, fetched once a seat is actually payable.
  useEffect(() => {
    if (formState !== 'success' || registrationId === null || priceCents <= 0) return;
    let cancelled = false;
    fetchPaymentsConfig().then((cfg) => {
      if (!cancelled) setPayCfg(cfg);
    });
    return () => {
      cancelled = true;
    };
  }, [formState, registrationId, priceCents]);

  const seatsRemaining =
    seatsTaken === null ? capacity : Math.max(0, capacity - seatsTaken);
  const atCapacity = seatsTaken !== null && seatsTaken >= capacity;
  const isFull = atCapacity || courseStatus === 'closed';
  const progressPct =
    seatsTaken === null ? 0 : Math.min(100, (seatsTaken / capacity) * 100);
  const priceLabel = formatAmount(priceCents, currency);
  const recordedPriceLabel = formatAmount(recordedPriceCents, 'usd');

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFormState('loading');
    setFormError(null);

    const form = e.currentTarget;
    const formData = new FormData(form);

    // Local preview without a backend: simulate success after a small delay.
    if (!REGISTER_ENDPOINT) {
      await new Promise((r) => setTimeout(r, 800));
      setFormState('success');
      return;
    }

    try {
      const payload = {
        ...Object.fromEntries(formData.entries()),
        course_code: COURSE_CODE,
      };
      const res = await fetch(REGISTER_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setFormError(data.detail || data.error || `Registration failed (${res.status}).`);
        setFormState('error');
        return;
      }
      if (typeof data.taken === 'number') setSeatsTaken(data.taken);
      if (typeof data.registration_id === 'number') setRegistrationId(data.registration_id);
      setFormState(data.status === 'duplicate' ? 'duplicate' : 'success');
    } catch {
      setFormError('Network error. Please try again or email info@proreadyengineer.com.');
      setFormState('error');
    }
  };

  // ----- Online payment for the held seat (PayPal capture / Stripe redirect)

  const createLiveOrder = async (): Promise<string> => {
    setPayError(null);
    const res = await fetch(`${API_BASE}/api/payments/live/paypal/create-order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ registration_id: registrationId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.order_id) {
      setPayError(
        typeof data.detail === 'string'
          ? data.detail
          : 'Could not start PayPal checkout. Please try again.',
      );
      throw new Error('paypal create-order failed');
    }
    return data.order_id as string;
  };

  const captureLiveOrder = async (orderId: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/api/payments/live/paypal/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ registration_id: registrationId, order_id: orderId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      setPayError(
        typeof data.detail === 'string'
          ? data.detail
          : 'PayPal could not complete this payment. Please try again.',
      );
      throw new Error('paypal capture failed');
    }
    setPaidNow(true);
  };

  const startCardCheckout = async () => {
    if (registrationId === null) return;
    setCardLoading(true);
    setPayError(null);
    try {
      const res = await fetch(`${API_BASE}/api/payments/live/stripe/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ registration_id: registrationId }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.url) {
        window.location.href = data.url;
        return;
      }
      setPayError(
        typeof data.detail === 'string'
          ? data.detail
          : 'Could not start card checkout. Please try again.',
      );
    } catch {
      setPayError('Network error. Please try again.');
    }
    setCardLoading(false);
  };

  const showPayPanel =
    registrationId !== null &&
    priceCents > 0 &&
    payCfg !== null &&
    (payCfg.paypal_enabled || payCfg.stripe_enabled);

  return (
    <div className="pb-20">
      {/* JSON-LD Course schema */}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: COURSE_JSONLD }} />

      {/* HERO */}
      <section className="relative pt-36 pb-12 lg:pt-44 overflow-hidden">
        <div className="hero-backdrop" />
        <div className="absolute inset-0 -z-10 bg-hero-radial" />
        <div className="container-site">
          <div className="anim-enter">
            <span className="eyebrow mb-5">Live Online Cohort</span>
            <h1 className="text-4xl md:text-6xl font-bold tracking-tight mt-4 mb-6 leading-tight">
              Micro Gas Turbine <span className="text-gradient">Design</span>
            </h1>
            <p className="text-xl md:text-2xl font-light text-slate-300 mb-8 max-w-3xl">
              Design a 700 N single-shaft turbojet end to end — live with the instructor,
              over seven half-day sessions.
            </p>

            {/* Key facts band — live data in mono */}
            <div className="flex flex-wrap gap-3 mb-10">
              <FactChip icon={<Clock className="w-3.5 h-3.5" aria-hidden="true" />}>
                {dayDates.length || CURRICULUM.length} days · 4 hours/day · live online
              </FactChip>
              <FactChip icon={<Calendar className="w-3.5 h-3.5" aria-hidden="true" />}>
                Next cohort: {cohortDate}
              </FactChip>
              <FactChip icon={<Users className="w-3.5 h-3.5" aria-hidden="true" />}>
                {seatsLoading
                  ? 'Seats: checking…'
                  : courseStatus === 'closed'
                    ? 'Registration closed'
                    : atCapacity
                      ? 'Cohort full'
                      : `${seatsRemaining}/${capacity} seats left`}
              </FactChip>
              <FactChip icon={<PlayCircle className="w-3.5 h-3.5" aria-hidden="true" />}>
                Recorded course included
              </FactChip>
            </div>

            <div className="flex flex-wrap items-center gap-4 mb-12">
              <a
                href="#register"
                onClick={(e) => {
                  e.preventDefault();
                  document
                    .getElementById('register')
                    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }}
                className="btn-primary text-base px-8 py-4"
              >
                Register
                <Send className="w-4 h-4" aria-hidden="true" />
              </a>
              <span className="text-sm text-slate-300">
                No payment required to register. Your seat is held as pending.
              </span>
            </div>

            {/* Course infographic — placed directly under the title, matching site pattern */}
            <div className="card overflow-hidden mb-10 shadow-2xl shadow-cyan-900/10">
              <img
                src="/Micro_Gas_Turbine_Design_Infographic.jpg"
                alt="Micro Gas Turbine Design — live online cohort: design a 700 N single-shaft turbojet end to end. Engine architecture and gas path, centrifugal compressor, evaporative combustor, axial turbine, compressor maps and surge, turbomachinery CFD, and combustor analysis. Seven live days of four hours each, with the complete recorded course included."
                className="w-full h-auto block"
                width={1200}
                loading="eager"
                fetchPriority="high"
              />
            </div>

            <p className="text-slate-300 text-lg mb-10 leading-relaxed max-w-4xl">
              This is the live edition of our Micro Gas Turbine Design programme — the same
              curriculum delivered to a national jet-engine development team, taught in real
              time over seven consecutive business days. One 700 N class reference engine runs
              through every session, so the compressor you size on day two is the compressor
              the turbine has to match on day four. You bring your questions to the instructor
              as the design unfolds, and you keep lifetime access to the complete recorded
              course after the live days end.
            </p>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat
                icon={<Clock className="w-5 h-5" aria-hidden="true" />}
                label="Duration"
                value={`${dayDates.length || CURRICULUM.length} Days × 4 Hours`}
              />

              <Stat
                icon={<Calendar className="w-5 h-5" aria-hidden="true" />}
                label="Next Cohort"
                value={cohortDate}
              />
              <Stat
                icon={<Users className="w-5 h-5" aria-hidden="true" />}
                label="Cohort Size"
                value={`${capacity} Seats`}
              />
              <Stat
                icon={<Award className="w-5 h-5" aria-hidden="true" />}
                label="Format"
                value="Live + Recorded"
              />
            </div>
          </div>
        </div>
      </section>

      <div className="container-site">
        {/* SEATS BAR */}
        <div className="anim-enter mb-16 p-6 md:p-8 card">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <div>
              <div className="text-xs font-mono uppercase tracking-wider text-slate-300 mb-1">
                Seat availability: {cohortDate} cohort
              </div>
              <div className="text-2xl font-bold">
                {seatsLoading ? (
                  <span className="text-slate-300">Loading…</span>
                ) : courseStatus === 'closed' ? (
                  <span className="text-amber-400">Registration closed</span>
                ) : atCapacity ? (
                  <span className="text-amber-400">Cohort full, waitlist only</span>
                ) : (
                  <span className="font-mono tabular-nums">
                    {seatsRemaining} of {capacity} seats remaining
                  </span>
                )}
              </div>
            </div>
            {isFull ? (
              <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-sm font-semibold">
                <Lock className="w-4 h-4" aria-hidden="true" /> Registration closed
              </span>
            ) : (
              <a
                href="#register"
                className="btn-primary"
              >
                Reserve my seat
              </a>
            )}
          </div>
          <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                isFull ? 'bg-amber-500' : 'bg-cyan-500'
              }`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* CURRICULUM TIMELINE — number of cards is driven by the admin's */}
        {/* day_dates list. Topics for each day come from the shared MODULES */}
        {/* array; days beyond CURRICULUM.length render as a TBD placeholder. */}
        <div className="mb-16">
          <span className="eyebrow mb-4">Curriculum</span>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-8">
            The {dayDates.length || CURRICULUM.length}-Day Arc
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {(dayDates.length > 0 ? dayDates : DEFAULT_DAY_DATES).map((dateLabel, i) => {
              const day = CURRICULUM[i] ?? TBD_DAY;
              return (
                <Reveal
                  key={i}
                  delay={i * 0.05}
                  className="card card-hover p-6 flex flex-col"
                >
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
                      {day.icon}
                    </div>
                    <div className="leading-tight">
                      <div className="text-xs font-mono uppercase tracking-wider text-slate-300">
                        Day {i + 1}
                      </div>
                      <div className="text-xs font-mono text-cyan-400 font-medium">{dateLabel}</div>
                    </div>
                  </div>
                  <h3 className="font-bold text-white mb-1 text-lg leading-tight">{day.title}</h3>
                  {day.chapters && (
                    <div className="text-[11px] font-mono text-slate-400 mb-2">{day.chapters}</div>
                  )}
                  <p className="text-slate-300 text-sm mb-4 leading-relaxed">{day.summary}</p>
                  <ul className="space-y-2">
                    {day.topics.map((t) => (
                      <li
                        key={t}
                        className="text-xs text-slate-300 flex gap-2 leading-relaxed"
                      >
                        <CheckCircle2 className="w-3 h-3 text-cyan-500/70 shrink-0 mt-0.5" aria-hidden="true" />
                        <span>{t}</span>
                      </li>
                    ))}
                  </ul>
                  {day.outcomes.length > 0 && (
                    <div className="mt-5 pt-4 border-t border-slate-800">
                      <div className="text-[11px] font-mono uppercase tracking-wider text-cyan-400 mb-2">
                        You leave able to
                      </div>
                      <ul className="space-y-1.5">
                        {day.outcomes.map((o) => (
                          <li key={o} className="text-xs text-slate-200 flex gap-2 leading-relaxed">
                            <span className="text-cyan-500/70 shrink-0" aria-hidden="true">→</span>
                            <span>{o}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </Reveal>
              );
            })}
          </div>
        </div>

        {/* DAILY SCHEDULE — applies to every cohort day. Times are fixed (no */}
        {/* DST drift handling): the course runs early October 2026 when North */}
        {/* America is still on DST, while Algeria + Saudi Arabia are DST-free */}
        {/* — the same offsets as the Emissions Mapping cohort. */}
        <Reveal className="mb-16">
          <span className="eyebrow mb-4">Daily Schedule</span>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-3">
            Same hours every day
          </h2>
          <p className="text-slate-300 text-base mb-8 max-w-2xl leading-relaxed">
            Four teaching hours with a 10-minute break between each, keeping focus high
            and fatigue low over seven consecutive business days (weekends off). Sessions
            stream live for all four time zones below.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {[
              { city: 'Vancouver', label: 'Pacific Time', start: '7:00 AM', end: '11:30 AM' },
              { city: 'New York', label: 'Eastern Time', start: '10:00 AM', end: '2:30 PM' },
              { city: 'Algeria', label: 'UTC+1', start: '3:00 PM', end: '7:30 PM' },
              { city: 'Saudi Arabia', label: 'UTC+3', start: '5:00 PM', end: '9:30 PM' },
            ].map((tz) => (
              <div
                key={tz.city}
                className="card card-hover p-5"
              >
                <div className="text-xs font-mono uppercase tracking-wider text-slate-300 mb-1">
                  {tz.label}
                </div>
                <div className="text-base font-semibold text-cyan-400 mb-3">{tz.city}</div>
                <div className="flex items-baseline gap-2 flex-wrap font-mono">
                  <span className="text-xl font-bold text-white tabular-nums">{tz.start}</span>
                  <span className="text-slate-500">→</span>
                  <span className="text-xl font-bold text-white tabular-nums">{tz.end}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Hour-by-hour ruler — anchored to Eastern Time so it stays compact */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div className="text-xs font-mono uppercase tracking-wider text-slate-300">
                Hour-by-hour · Eastern Time
              </div>
              <div className="text-[11px] text-slate-300">10-minute break between hours</div>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { n: 1, time: '10:00 – 11:00' },
                { n: 2, time: '11:10 – 12:10' },
                { n: 3, time: '12:20 – 13:20' },
                { n: 4, time: '13:30 – 14:30' },
              ].map(({ n, time }) => (
                <div
                  key={n}
                  className="px-3 py-2 rounded-lg bg-slate-950/60 border border-slate-800 flex items-center gap-2"
                >
                  <span className="text-[10px] font-mono uppercase tracking-wider text-slate-300 shrink-0">
                    Hr {n}
                  </span>
                  <span className="text-slate-200 font-mono tabular-nums text-xs">{time}</span>
                </div>
              ))}
            </div>
          </div>
        </Reveal>

        {/* PRICING — live seat with the recorded course included */}
        <Reveal className="mb-16">
          <span className="eyebrow mb-4">Pricing</span>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-3">
            Live Cohort Pricing
          </h2>
          <p className="text-slate-300 text-base mb-8 max-w-2xl leading-relaxed">
            One price per seat, and the complete recorded course is included — the material
            stays with you for good after the live days end.
          </p>

          {/* Price hero */}
          <div className="relative rounded-2xl bg-gradient-to-br from-cyan-900/20 via-slate-900/60 to-blue-900/20 border border-cyan-500/30 p-8 md:p-10 mb-8 overflow-hidden">
            <div
              className="absolute -top-24 -right-16 w-72 h-72 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-6 relative">
              <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-500/15 border border-cyan-500/40 text-cyan-200 text-xs font-mono uppercase tracking-wider mb-4">
                  <PlayCircle className="w-3.5 h-3.5" aria-hidden="true" />
                  Recorded course included
                </div>
                <div className="text-3xl md:text-4xl font-bold text-white mb-2">
                  {priceLabel}{' '}
                  <span className="text-lg font-normal text-slate-300">per seat</span>
                </div>
                <p className="text-slate-300 text-sm leading-relaxed max-w-xl">
                  Your seat covers all seven live sessions plus lifetime access to the
                  complete recorded course — every video, design calculator, interactive tool
                  and quiz. Register with no payment to hold your seat, then pay online or by
                  invoice.
                </p>
              </div>
              <div className="flex flex-col gap-3 shrink-0">
                <a
                  href="#register"
                  className="btn-primary text-base px-8 py-4"
                >
                  Reserve my seat
                  <Send className="w-4 h-4" aria-hidden="true" />
                </a>
                <Link
                  to="/training/micro-gas-turbine-design"
                  className="text-center text-sm text-cyan-300 hover:text-cyan-200 underline"
                >
                  Prefer self-paced? Recorded edition — {recordedPriceLabel}
                </Link>
              </div>
            </div>
          </div>

          {/* Value framing */}
          <div className="space-y-4 prose-dark mb-10 max-w-3xl">
            <p>
              Your seat includes live instructor-led training across all seven design
              modules, direct access to the instructor as the reference engine takes shape,
              and the complete recorded course to revisit any derivation afterwards.
            </p>
            <p>
              This cohort is designed to take you through a real design sequence: the
              architecture and materials on day one become the compressor you size on day
              two, the combustor you analyse on day seven — one 700 N engine, carried end to
              end.
            </p>
            <p className="text-slate-300">
              You are not just attending a class. You are working a complete engine design
              with an instructor who has delivered this programme to a national jet-engine
              development team.
            </p>
          </div>

          {/* Included grid */}
          <span className="eyebrow mb-4">What You Get with Your Seat</span>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8 mt-4">
            {[
              {
                icon: <Users className="w-5 h-5" aria-hidden="true" />,
                title: 'Seven Live Sessions with Bassam Abdelnabi',
                body: 'Four focused hours a day over consecutive business days, taught in real time by the engineer who built and delivered this programme.',
              },
              {
                icon: <MessageSquare className="w-5 h-5" aria-hidden="true" />,
                title: 'Direct Q&A During the Course',
                body: 'Ask your specific questions as each design decision is made, and connect the material to your own engine or project.',
              },
              {
                icon: <InfinityIcon className="w-5 h-5" aria-hidden="true" />,
                title: 'Full Recorded Course Included',
                body: 'Lifetime access to the complete on-demand edition — all seven modules, 16 hours of recorded video, slide decks and updates — in your own browser account.',
              },
              {
                icon: <Wrench className="w-5 h-5" aria-hidden="true" />,
                title: 'Design Calculators & Interactive Tools',
                body: 'The four design calculators and two interactive tools used in the sessions, so you can rerun every sizing decision on your own numbers.',
              },
              {
                icon: <Gauge className="w-5 h-5" aria-hidden="true" />,
                title: 'One Reference Engine, End to End',
                body: 'A 700 N class engine runs through every session: the compressor you size in one module is the compressor the turbine has to match in another.',
              },
              {
                icon: <Award className="w-5 h-5" aria-hidden="true" />,
                title: 'Quizzes and a Verifiable Certificate',
                body: 'Module quizzes track your understanding, and the course closes with a certificate carrying public verification.',
              },
            ].map((item) => (
              <div
                key={item.title}
                className="card card-hover p-5 flex flex-col"
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-9 h-9 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shrink-0">
                    {item.icon}
                  </div>
                  <h3 className="font-semibold text-white text-sm leading-tight">{item.title}</h3>
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">{item.body}</p>
              </div>
            ))}
          </div>

          {/* Groups */}
          <p className="text-slate-300 text-sm leading-relaxed">
            For teams enrolling multiple engineers,{' '}
            <Link to="/contact" className="text-cyan-400 hover:text-cyan-300 underline">
              contact ProReadyEngineer
            </Link>{' '}
            for group registration options.
          </p>
        </Reveal>

        {/* INSTRUCTOR */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-16">
          <div className="lg:col-span-2 p-8 card">
            <span className="eyebrow mb-4">Led By</span>
            <h2 className="text-3xl font-bold tracking-tight mt-4 mb-4">Bassam Abdelnabi</h2>
            <p className="text-slate-300 leading-relaxed mb-4">
              Founder of ProReadyEngineer. 19+ years in gas-turbine combustion and test
              engineering, with multiple patents in gas-turbine combustion and emissions
              reduction. This programme was built for and delivered to a national jet-engine
              development team, and the live cohort teaches it the same way: one real engine,
              every decision worked through with its numbers. See reviews in the{' '}
              <Link to="/testimonials" className="text-cyan-400 hover:text-cyan-300 underline">
                Testimonials section
              </Link>
              {' '}on proreadyengineer.com.
            </p>
            <p className="text-slate-300 text-sm leading-relaxed">
              The course is built around field-grade design decisions, not textbook theory.
              Every session answers "what do you size, check and verify next" on a machine
              that has to run — not "what does the textbook say."
            </p>
          </div>
          <div className="p-8 card">
            <span className="eyebrow mb-4">Ideal For</span>
            <ul className="space-y-3 mt-4">
              {IDEAL_FOR.map((x) => (
                <li key={x} className="flex items-center gap-3 text-slate-300">
                  <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
                  <span>{x}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-slate-300 mt-6 leading-relaxed">
              An engineering background helps, but every derivation is built from first
              principles on the reference engine. You'll leave able to size, check and
              analyse a small turbojet end to end.
            </p>
          </div>
        </div>

        {/* REGISTRATION FORM */}
        <Reveal id="register" className="p-8 md:p-12 card scroll-mt-28">
          {returnBanner === 'paid' && (
            <div className="mb-8 p-4 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-200 text-sm flex items-start gap-3">
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                Payment received — your seat is confirmed. A receipt is on its way to your
                email.
              </span>
            </div>
          )}
          {returnBanner === 'cancelled' && (
            <div className="mb-8 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-sm flex items-start gap-3">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                Checkout was cancelled — nothing was charged. Your seat is still held; we'll
                email payment instructions, or write to{' '}
                <a className="underline" href="mailto:info@proreadyengineer.com">
                  info@proreadyengineer.com
                </a>
                .
              </span>
            </div>
          )}
          <span className="eyebrow mb-4">Register</span>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-2">
            Reserve your seat — {cohortDate} cohort
          </h2>
          <p className="text-slate-300 mb-8 font-mono text-sm">
            {courseStatus === 'closed'
              ? 'Registration is closed for this cohort.'
              : atCapacity
                ? `All ${capacity} seats are taken. Join the waitlist for the next cohort.`
                : `${seatsRemaining} of ${capacity} seats remaining.`}
          </p>

          {formState === 'success' ? (
            <div className="text-center py-12">
              <div className="w-20 h-20 bg-cyan-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <CheckCircle2 className="w-10 h-10 text-cyan-400" aria-hidden="true" />
              </div>
              {paidNow ? (
                <>
                  <h3 className="text-2xl font-bold mb-4">
                    Payment received — your seat is confirmed
                  </h3>
                  <p className="text-slate-300 mb-8 max-w-md mx-auto">
                    A receipt is on its way to your inbox, and the pre-read material follows
                    closer to the start date. Questions in the meantime? Email{' '}
                    <a
                      className="text-cyan-400 underline"
                      href="mailto:info@proreadyengineer.com"
                    >
                      info@proreadyengineer.com
                    </a>
                    .
                  </p>
                </>
              ) : (
                <>
                  <h3 className="text-2xl font-bold mb-4">Registration received</h3>
                  <p className="text-slate-300 mb-8 max-w-md mx-auto">
                    Thanks — we'll send a confirmation email with payment details and pre-read
                    material within 24 hours. If you don't see it, check spam or email{' '}
                    <a
                      className="text-cyan-400 underline"
                      href="mailto:info@proreadyengineer.com"
                    >
                      info@proreadyengineer.com
                    </a>
                    .
                  </p>
                  {showPayPanel && payCfg && (
                    <div className="max-w-md mx-auto text-left rounded-2xl border border-cyan-500/30 bg-slate-900/60 p-6">
                      <h4 className="text-lg font-bold text-white mb-1">Secure your seat now</h4>
                      <p className="text-sm text-slate-300 mb-5">
                        Live cohort seat —{' '}
                        <span className="text-white font-semibold">
                          {formatAmount(priceCents, currency)}
                        </span>
                      </p>
                      {payError && (
                        <p className="text-sm text-amber-300 mb-3" role="alert">
                          {payError}
                        </p>
                      )}
                      {payCfg.paypal_enabled && (
                        <div className="mb-3">
                          <p className="text-xs font-mono uppercase tracking-wider text-slate-300 mb-2">
                            Pay with PayPal
                          </p>
                          <PayPalButtons
                            createOrder={createLiveOrder}
                            onApprove={captureLiveOrder}
                          />
                        </div>
                      )}
                      {payCfg.stripe_enabled && (
                        <button
                          type="button"
                          onClick={startCardCheckout}
                          disabled={cardLoading}
                          className="btn-secondary w-full disabled:opacity-70 disabled:cursor-wait"
                        >
                          {cardLoading ? 'Opening checkout…' : 'Pay by card'}
                        </button>
                      )}
                      <p className="text-xs text-slate-400 mt-4">
                        Tip: choosing "US bank account" at checkout costs far less in processing
                        fees than a card, and helps us keep course prices down.
                      </p>
                      <p className="text-xs text-slate-400 mt-2">
                        Prefer Zelle or an invoice? Your seat is held.{' '}
                        <Link to="/contact" className="text-cyan-400 hover:text-cyan-300">
                          Contact us
                        </Link>{' '}
                        and we'll send an invoice with Zelle and bank-transfer details.
                      </p>
                    </div>
                  )}
                </>
              )}
            </div>
          ) : formState === 'duplicate' ? (
            <div className="text-center py-12">
              <div className="w-20 h-20 bg-cyan-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <CheckCircle2 className="w-10 h-10 text-cyan-400" aria-hidden="true" />
              </div>
              <h3 className="text-2xl font-bold mb-4">You're already registered</h3>
              <p className="text-slate-300 mb-8 max-w-md mx-auto">
                We already have a registration for this email address. Watch your inbox for
                payment details — or email{' '}
                <a
                  className="text-cyan-400 underline"
                  href="mailto:info@proreadyengineer.com"
                >
                  info@proreadyengineer.com
                </a>{' '}
                if you didn't receive the confirmation.
              </p>
            </div>
          ) : isFull ? (
            <div className="text-center py-12">
              <div className="w-20 h-20 bg-amber-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <Lock className="w-10 h-10 text-amber-400" aria-hidden="true" />
              </div>
              <h3 className="text-2xl font-bold mb-4">
                {courseStatus === 'closed' ? 'Registration closed' : 'Cohort full'}
              </h3>
              <p className="text-slate-300 mb-8 max-w-md mx-auto">
                {courseStatus === 'closed'
                  ? `Registration for the ${cohortDate} cohort is closed.`
                  : `All ${capacity} seats for the ${cohortDate} cohort are taken.`}{' '}
                Email{' '}
                <a
                  className="text-cyan-400 underline"
                  href="mailto:info@proreadyengineer.com?subject=Waitlist — Micro Gas Turbine Design Live Cohort"
                >
                  info@proreadyengineer.com
                </a>{' '}
                to join the waitlist for the next cohort.
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-6">
              {formState === 'error' && formError && (
                <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm flex items-start gap-3">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
                  <span>{formError}</span>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Field label="Full Name" name="full_name" required placeholder="Jane Doe" />
                <Field
                  label="Email"
                  name="email"
                  type="email"
                  required
                  placeholder="you@example.com"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Field
                  label="Job Title"
                  name="job_title"
                  required
                  placeholder="Propulsion Engineer"
                />
                <Field
                  label="Company"
                  name="company"
                  required
                  placeholder="Engineering Corp"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label htmlFor="years_experience" className="text-xs font-medium text-slate-300 uppercase tracking-wider ml-1">
                    Years of Experience <span className="text-cyan-400" aria-hidden="true">*</span>
                  </label>
                  <select
                    id="years_experience"
                    name="years_experience"
                    required
                    className="w-full bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-cyan-400 transition-colors text-slate-200"
                    defaultValue=""
                  >
                    <option value="" disabled>
                      Select…
                    </option>
                    <option value="0-2">0–2 years</option>
                    <option value="3-5">3–5 years</option>
                    <option value="6-10">6–10 years</option>
                    <option value="11-20">11–20 years</option>
                    <option value="20+">20+ years</option>
                  </select>
                </div>
                <Field
                  label="Location (City, Country)"
                  name="location"
                  required
                  placeholder="Cincinnati, USA"
                />
              </div>

              {/* Honeypot — hidden from real users, filled by bots. Submissions with a
                  non-empty `website` value are silently dropped by the backend. Do NOT add
                  `autocomplete="off"` — browsers will still autofill URL fields if labelled
                  like a real one; leaving it plain works better with most bots. */}
              <div aria-hidden="true" style={{ position: 'absolute', left: '-9999px' }}>
                <label>
                  Website (leave blank)
                  <input type="text" name="website" tabIndex={-1} autoComplete="off" />
                </label>
              </div>

              <label className="flex items-start gap-3 text-xs text-slate-300 leading-relaxed">
                <input
                  type="checkbox"
                  name="consent"
                  required
                  className="mt-0.5 accent-cyan-500"
                />
                <span>
                  I consent to ProReadyEngineer using my details to process my registration and
                  send course-related communications. I can request deletion at any time by
                  emailing info@proreadyengineer.com.
                </span>
              </label>

              <button
                type="submit"
                disabled={formState === 'loading'}
                className="btn-primary w-full flex items-center justify-center gap-2 py-4 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {formState === 'loading' ? 'Submitting…' : 'Reserve my seat'}{' '}
                <Send className="w-4 h-4" aria-hidden="true" />
              </button>

              <p className="text-[10px] text-slate-300 text-center uppercase tracking-widest font-mono">
                Secure · {capacity} seats per cohort · Auto-locks when full
              </p>
            </form>
          )}
        </Reveal>
      </div>
    </div>
  );
};

// -----------------------------------------------------------------------------
// Small helpers
// -----------------------------------------------------------------------------
const FactChip = ({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) => (
  <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/70 border border-slate-700/80 text-xs font-mono text-slate-300">
    <span className="text-cyan-400">{icon}</span>
    {children}
  </span>
);

const Stat = ({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) => (
  <div className="p-4 card">
    <div className="flex items-center gap-2 text-cyan-400 mb-2">{icon}</div>
    <div className="text-xs font-mono uppercase tracking-wider text-slate-300 mb-1">
      {label}
    </div>
    <div className="text-sm font-bold text-white font-mono">{value}</div>
  </div>
);

const Field = ({
  label,
  name,
  type = 'text',
  required,
  placeholder,
}: {
  label: string;
  name: string;
  type?: string;
  required?: boolean;
  placeholder?: string;
}) => (
  <div className="space-y-2">
    <label htmlFor={name} className="text-xs font-medium text-slate-300 uppercase tracking-wider ml-1">
      {label}{required && <span className="text-cyan-400" aria-hidden="true"> *</span>}
    </label>
    <input
      id={name}
      name={name}
      type={type}
      required={required}
      placeholder={placeholder}
      className="w-full bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-400 transition-colors"
    />
  </div>
);

export default MicroGasTurbineDesignLive;
