import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Calendar,
  Users,
  Clock,
  Award,
  Flame,
  Activity,
  Gauge,
  Wrench,
  CheckCircle2,
  Lock,
  MessageSquare,
  Send,
  AlertTriangle,
  Sparkles,
} from 'lucide-react';
import { Reveal } from '../../components/ui';
import PayPalButtons, { fetchPaymentsConfig, PaymentsConfig } from '../../components/PayPalButtons';
import { usePageMeta } from '../../lib/meta';
import {
  formatIsoDate as formatStartDate,
  snapshotDayLabels,
  snapshotStartLabel,
} from '../../data/courseSnapshot';

// -----------------------------------------------------------------------------
// Course constants
// -----------------------------------------------------------------------------
// Course code matches the backend Course.code. Start date + seats are now
// fetched from /api/courses/{code}; the constants below are fallbacks for
// local preview before the backend is reachable.
const COURSE_CODE = 'gas-turbine-emissions-mapping-2026-05';
const DEFAULT_CAPACITY = 15;
// Founding Cohort seat price and the regular rate it is discounted from.
// The live price comes from the course record at runtime; this default keeps
// the prerendered HTML honest until that fetch lands.
const DEFAULT_PRICE_CENTS = 150000;
const REGULAR_PRICE_CENTS = 450000;
// Prerender fallback for the cohort start, taken from the build-time snapshot
// of the live course record (see data/courseSnapshot). The literal is only a
// last resort for a course the build has never been able to reach.
const DEFAULT_COHORT_DATE = snapshotStartLabel(COURSE_CODE, 'August 29, 2026');

// Backend endpoints. Set VITE_API_BASE in your deploy env to the Render URL,
// e.g. https://proreadyengineer-training-api.onrender.com
// When unset (local dev without backend), the form simulates success so the UI
// can be previewed without the API running.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';
const COURSE_ENDPOINT = API_BASE ? `${API_BASE}/api/courses/${COURSE_CODE}` : '';
const REGISTER_ENDPOINT = API_BASE ? `${API_BASE}/api/register` : '';

// 149500 + 'usd' -> "$1,495"; keeps cents only when they exist.
const formatAmount = (cents: number, currency: string): string =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: (currency || 'usd').toUpperCase(),
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);

// formatStartDate (ISO -> "August 29, 2026", no timezone drift) is imported
// above from data/courseSnapshot so the build script and the page agree.

// JSON-LD Course schema for search engines.
const COURSE_JSONLD = JSON.stringify({
  '@context': 'https://schema.org',
  '@type': 'Course',
  name: 'Gas Turbine Emissions Mapping',
  description:
    
    'Four-day live expert course (two weekends) on DLE gas turbine emissions mapping, built on 194 slides across 10 chapters: combustion and gas turbine fundamentals, combustion dynamics and DLE combustion system operation, NOx/CO and EPA Method 7E CEMS, the step-by-step mapping procedure practised on a simulated combustion system, then ambient effects, flex fuel and field troubleshooting. Taught by a practitioner with 19+ years of field mapping experience.',
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
// This mirrors the delivered material one-to-one: the chapter split, the
// slide counts and the outcomes are taken from the four day decks and from
// the learning objectives loaded against each module on the platform. If a
// deck changes, change this too — a buyer comparing the advertised agenda
// with the material they receive should find no gap.
type Day = {
  title: string;
  chapters: string;
  summary: string;
  topics: string[];
  outcomes: string[];
  icon: React.ReactNode;
};

const CURRICULUM: Day[] = [
  {
    title: 'Combustion & Gas Turbine Fundamentals',
    chapters: 'Chapters 1–2 · 55 slides',
    summary:
      'The physics you need before you can tune anything: how flames behave, what sets flame temperature and NOx, and how a DLE machine is actually built — from premixer to metering valve.',
    topics: [
      'Premixed, diffusion and partially-premixed flames — and why DLE chose premixed',
      'Equivalence ratio φ, the lean operating window, and adiabatic flame temperature',
      'Thermal NOx (Zeldovich) and its exponential sensitivity to flame temperature',
      'Laminar flame speed compared: methane, heavier hydrocarbons, hydrogen',
      'Flashback, lean blowout and flame lift-off — mechanisms, precursors, protection',
      'Brayton cycle, gas turbine architectures, and DLE vs diffusion (SAC) philosophy',
      'Hardware: swirler, premixer, liner, transition piece, fuel nozzle',
      'Fuel supply chain: staging valves, metering valves and the float circuit',
    ],
    outcomes: [
      'Classify any flame and predict its temperature, NOx and stability signature',
      'Read a fuel-composition change and infer the flashback and NOx consequence',
      'Say what each valve and sensor does — and what happens in the combustor when it degrades',
    ],
    icon: <Flame className="w-6 h-6" />,
  },
  {
    title: 'Combustion Dynamics & DLE Operation',
    chapters: 'Chapters 3–4 · 45 slides',
    summary:
      'Why premixed flames sing, what the amplitude limits actually oblige you to do, and how a combustion system is staged and controlled.',
    topics: [
      'Thermoacoustic instability and the Rayleigh criterion — when an oscillation grows',
      'LFD and HFD amplitude bands, and the action each band requires',
      'Protection hierarchy: E-ABAL → BRNUL → stage down → trip',
      'High-cycle fatigue — what dynamics does to hardware, and how fast',
      'Dynamic pressure sensors, sampling rate, signal processing and damping',
      'Combustion system fuel circuits, burner modes and mode-transition risks',
      'The key limiting tones: where each appears and the correct first action',
      'Fuel orifices — what they fix, how they are identified, when to swap',
      'Control schedules, operating-window boundaries and remapping triggers',
    ],
    outcomes: [
      'Decide from a described oscillation whether it will grow or decay',
      'Place a measured amplitude in the right band and take the right protective action',
      'Move pilot split, ELBO and TFlame the correct direction — and state the NOx cost',
    ],
    icon: <Activity className="w-6 h-6" />,
  },
  {
    title: 'Emissions, CEMS & Combustion Mapping',
    chapters: 'Chapters 5–6 · 47 slides + simulator',
    summary:
      'Where NOx and CO come from, how they are legally measured, and then the mapping procedure itself — worked step by step on a simulated combustion system.',
    topics: [
      'NOx pathways (thermal, prompt, fuel-bound, N₂O); CO formation, quench and LBO proximity',
      'Extractive vs in-situ CEMS, and the EPA Method 7E sampling train',
      'Analyzers compared: CLD, NDIR and O₂ cells; probe siting and heated sample lines',
      'Calibration drift against the ±2.5%-of-span limit, and emissions data QA',
      'Regulatory corrections: 15% O₂, dry basis, ISO conditions',
      'Per-circuit emissions and acoustics response',
      'IGV settings versus load, and part-load CO',
      'Mapping preparation, safety protocols, tools, and the step-by-step procedure',
      'Cold-tune / hot-check discipline across fuel temperature',
      'Updating fuel circuits mapping tables, plus the remote tuning bias table',
      'Operating-line verification and mapping documentation requirements',
    ],
    outcomes: [
      'Correct raw analyzer readings to 15% O₂ dry, and judge a daily drift check',
      'Run a full mapping sequence on the simulated combustion system, inside the mapping window',
      'Produce as-left mapping tables and release an engine with the right evidence behind it',
    ],
    icon: <Gauge className="w-6 h-6" />,
  },
  {
    title: 'Ambient, Flex Fuel & Troubleshooting',
    chapters: 'Chapters 7–10 · 47 slides',
    summary:
      'What moves your map after you have set it — weather, fuel and failing instruments — and how to tell a real combustion event from a sensor lying to you.',
    topics: [
      'Inlet temperature, pressure, humidity and altitude effects on NOx, stability and output',
      'Ambient correction strategies and seasonal remapping',
      'Wobbe Index and Modified Wobbe Index: the ±3% alarm, ±5% action and ±10% trip bands',
      'Acoustic response to fuel-composition change; LNG-C strategies and measurement time delay',
      'Hydrogen blending: flame speed, flame position, convective delay and flashback risk',
      'Sensor failures — dynamic pressure, thermocouple and emissions — and their signatures',
      'Acoustic spikes, system freeze, wrong-circuit wiring, and calibration error propagation',
      'Root-cause analysis for LBO, flashback and stage-down events',
      'Field case studies: LBO during load rejection, and a commissioning wiring error',
      'Course review, operational best practices, and the common pitfalls to avoid',
    ],
    outcomes: [
      'State which way NOx, stability and power move for any ambient change',
      'Decide whether a fuel change needs a schedule correction, a remap, or hardware',
      'Separate a failing sensor from a genuine combustion event in unit data',
    ],
    icon: <Wrench className="w-6 h-6" />,
  },
];

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
  'Field Mappers',
  'Commissioning Engineers',
  'Plant Operators',
  'Gas Turbine Experts',
  'Combustion Enthusiasts',
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
  'August 29, 2026',
  'August 30, 2026',
  'September 5, 2026',
  'September 6, 2026',
]);

const GasTurbineEmissionsMapping = () => {
  usePageMeta(
    'Gas Turbine Emissions Mapping Course',
    
    'Four-day live expert course, held over two weekends, on DLE gas turbine emissions mapping: combustion and GT fundamentals, dynamics and DLE combustion system operation, CEMS and the full mapping procedure on a simulator, then ambient, flex fuel and troubleshooting. Taught by a practitioner with 19+ years of field experience.',
    {
      image: 'https://proreadyengineer.com/Mapping_Course_Advertisement.png',
      jsonLd: {
        '@context': 'https://schema.org',
        '@type': 'Course',
        name: 'Gas Turbine Emissions Mapping',
        description:
          
            'Four-day live expert course, held over two weekends, on DLE gas turbine emissions mapping: combustion and GT fundamentals, dynamics and DLE combustion system operation, CEMS and the full mapping procedure on a simulator, then ambient, flex fuel and troubleshooting. Taught by a practitioner with 19+ years of field experience.',
        provider: { '@id': 'https://proreadyengineer.com/#org' },
        hasCourseInstance: [
          {
            '@type': 'CourseInstance',
            courseMode: 'Online',
            courseWorkload: 'P4D',
            instructor: { '@type': 'Person', name: 'Dr. Bassam Abdelnabi', jobTitle: 'Principal Consultant, Gas Turbine Combustion Expert' },
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
  // Per-day dates (formatted "May 16, 2026"). Defaults to the hardcoded
  // schedule above; replaced by the API list when day_dates is non-empty.
  const [dayDates, setDayDates] = useState<string[]>(DEFAULT_DAY_DATES);
  const [formState, setFormState] = useState<'idle' | 'loading' | 'success' | 'duplicate' | 'error'>(
    'idle',
  );
  const [formError, setFormError] = useState<string | null>(null);
  // Online payment for the held seat. registrationId only exists after a real
  // (non-simulated) /api/register success; priceCents comes from the course
  // record. The cohort has a public per-seat price now, so the fallback is
  // the real price rather than the old invoice-only 0.
  const [priceCents, setPriceCents] = useState<number>(DEFAULT_PRICE_CENTS);
  const [currency, setCurrency] = useState<string>('usd');
  const [registrationId, setRegistrationId] = useState<number | null>(null);
  const [payCfg, setPayCfg] = useState<PaymentsConfig | null>(null);
  const [paidNow, setPaidNow] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const [cardLoading, setCardLoading] = useState(false);
  // Stripe Checkout returns to this page with ?paid=1 / ?cancelled=1.
  const [returnBanner, setReturnBanner] = useState<'paid' | 'cancelled' | null>(null);

  // Fetch live course data (start_date + seats). Falls back to hardcoded
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

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFormState('loading');
    setFormError(null);

    const form = e.currentTarget;
    const formData = new FormData(form);

    // Phase 1: no backend wired — simulate success after a small delay.
    // Phase 2: POST to REGISTER_ENDPOINT.
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
            <span className="eyebrow mb-5">Flagship Course</span>
            <h1 className="text-4xl md:text-6xl font-bold tracking-tight mt-4 mb-6 leading-tight">
              Gas Turbine <span className="text-gradient">Emissions Mapping</span>
            </h1>
            <p className="text-xl md:text-2xl font-light text-slate-300 mb-8 max-w-3xl">
              De-mystifying complexity: the gas turbine mapping expert course.
            </p>

            {/* Key facts band — live data in mono */}
            <div className="flex flex-wrap gap-3 mb-10">
              <FactChip icon={<Clock className="w-3.5 h-3.5" aria-hidden="true" />}>
                {dayDates.length || CURRICULUM.length} days · live online
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
              <FactChip icon={<Sparkles className="w-3.5 h-3.5" aria-hidden="true" />}>
                {formatAmount(priceCents, currency)} per seat · over 60% off
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
                src="/Mapping_Course_Advertisement.png"
                alt="Gas Turbine Emissions Mapping — flagship live online course: from zero to field-ready in 4 live days. Day 1 combustion and gas turbine fundamentals, Day 2 combustion dynamics and DLE operation, Day 3 emissions, CEMS and the live mapping simulator, Day 4 ambient, flex fuel and troubleshooting. 194 slides, mapping simulator, daily mastery checks, quiz and interview for certification. Led by Bassam Abdelnabi. Next cohort August 29, 2026."
                className="w-full h-auto block"
                width={1671}
                height={941}
                loading="eager"
                fetchPriority="high"
              />
            </div>

            <p className="text-slate-300 text-lg mb-10 leading-relaxed max-w-4xl">
              Modern DLE combustion systems look daunting: five distinct gas circuits, bounded by
              narrow dynamics corridors and moving ambient targets. This course takes you from
              zero gas-turbine knowledge to confident field mapper over four days, taught by a
              practitioner with 19+ years of live mapping experience and multiple patents in the
              field.
            </p>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat
                icon={<Clock className="w-5 h-5" aria-hidden="true" />}
                label="Duration"
                value={`${dayDates.length || CURRICULUM.length} Days`}
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
                label="Level"
                value="Beginner → Expert"
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
        {/* day_dates list. Topics for each day come from the local CURRICULUM */}
        {/* array; days beyond CURRICULUM.length render as a TBD placeholder. */}
        <div className="mb-16">
          <span className="eyebrow mb-4">Curriculum</span>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-8">
            The {dayDates.length || CURRICULUM.length}-Day Arc
          </h2>
          {/* Two wide columns rather than one narrow column per day: the
              agenda now carries the real chapter detail, and five cramped
              columns made a 4-day course render with an empty slot. */}
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
        {/* DST drift handling): the course runs Aug-Sep 2026 when North */}
        {/* America is on DST, while Algeria + Saudi Arabia are DST-free. */}
        <Reveal className="mb-16">
          <span className="eyebrow mb-4">Daily Schedule</span>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-3">
            Same hours every day
          </h2>
          <p className="text-slate-300 text-base mb-8 max-w-2xl leading-relaxed">
            Five teaching hours with a 10-minute break between each, keeping focus high
            and fatigue low. Sessions stream live for all four time zones below.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {[
              { city: 'Vancouver', label: 'Pacific Time', start: '7:00 AM', end: '12:40 PM' },
              { city: 'New York', label: 'Eastern Time', start: '10:00 AM', end: '3:40 PM' },
              { city: 'Algeria', label: 'UTC+1', start: '3:00 PM', end: '8:40 PM' },
              { city: 'Saudi Arabia', label: 'UTC+3', start: '5:00 PM', end: '10:40 PM' },
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
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
              {[
                { n: 1, time: '10:00 – 11:00' },
                { n: 2, time: '11:10 – 12:10' },
                { n: 3, time: '12:20 – 13:20' },
                { n: 4, time: '13:30 – 14:30' },
                { n: 5, time: '14:40 – 15:40' },
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

        {/* COURSE MAP INFOGRAPHIC */}
        <Reveal className="mb-16 card overflow-hidden">
          <img
            src="/Mapping_Course_Advertisement.png"
            alt="Course overview — the four live days, what each covers, and what is included: 194 slides, the mapping simulator, daily mastery checks, and the certification quiz and interview."
            className="w-full h-auto block"
            width={1671}
            height={941}
            loading="lazy"
          />
        </Reveal>

        {/* PRICING — Founding Cohort offer for the first live cohort */}
        <Reveal className="mb-16">
          <span className="eyebrow mb-4">Pricing</span>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-3">
            Founding Cohort Pricing
          </h2>
          <p className="text-slate-300 text-base mb-8 max-w-2xl leading-relaxed">
            For the first live offering, this advanced training is available at a special
            Founding Cohort price.
          </p>

          {/* Price hero — Founding Cohort price with the regular rate anchored */}
          <div className="relative rounded-2xl bg-gradient-to-br from-cyan-900/20 via-slate-900/60 to-blue-900/20 border border-cyan-500/30 p-8 md:p-10 mb-8 overflow-hidden">
            <div
              className="absolute -top-24 -right-16 w-72 h-72 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-6 relative">
              <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-200 text-xs font-mono uppercase tracking-wider mb-4">
                  <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
                  Over 60% Founding Cohort discount
                </div>
                <div className="flex items-baseline gap-3 flex-wrap mb-2">
                  <span className="text-3xl md:text-4xl font-bold text-white tabular-nums">
                    {formatAmount(priceCents, currency)}
                  </span>
                  <span className="text-lg text-slate-400 line-through tabular-nums">
                    {formatAmount(REGULAR_PRICE_CENTS, currency)}
                  </span>
                  <span className="text-lg font-normal text-slate-300">per seat</span>
                </div>
                <p className="text-slate-300 text-sm leading-relaxed max-w-xl">
                  The Founding Cohort price is over 60% off the regular{' '}
                  {formatAmount(REGULAR_PRICE_CENTS, currency)} per-seat rate. Register with
                  no payment to hold your seat, then pay online or by invoice.
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
                  to="/contact"
                  className="text-center text-sm text-cyan-300 hover:text-cyan-200 underline"
                >
                  Questions? Contact us
                </Link>
              </div>
            </div>
          </div>

          {/* Value framing */}
          <div className="space-y-4 prose-dark mb-10 max-w-3xl">
            <p>
              Your seat includes live instructor-led training, interactive mapping
              simulator access, course materials, and the opportunity to ask your questions
              directly during the live sessions.
            </p>
            <p>
              This course is designed to help you understand the real logic behind gas turbine
              emissions mapping, including fuel splits, NOx, CO, combustion dynamics, safe
              operating windows, and practical mapping decisions.
            </p>
            <p className="text-slate-300">
              You are not just attending a class. You are building practical mapping
              understanding through expert instruction, realistic simulator-based learning,
              and direct interaction with the instructor.
            </p>
          </div>

          {/* Included grid */}
          <span className="eyebrow mb-4">What You Get with Your Seat</span>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8 mt-4">
            {[
              {
                icon: <Activity className="w-5 h-5" aria-hidden="true" />,
                title: 'Interactive Mapping Simulator',
                body: 'Use a realistic simulator to see how mapping decisions affect fuel splits, NOx, CO, combustion dynamics, and safe operating windows.',
              },
              {
                icon: <Users className="w-5 h-5" aria-hidden="true" />,
                title: 'Live Training with Bassam Abdelnabi',
                body: 'Learn directly from an instructor with deep real-world gas turbine combustion and mapping experience.',
              },
              {
                icon: <MessageSquare className="w-5 h-5" aria-hidden="true" />,
                title: 'Direct Q&A During the Course',
                body: 'Ask your specific questions during the live sessions and connect the training concepts to real field situations.',
              },
              {
                icon: <Wrench className="w-5 h-5" aria-hidden="true" />,
                title: 'Practical Mapping Examples',
                body: 'Work through examples that connect fuel splits, emissions behavior, dynamics, operability, and safe mapping decisions.',
              },
              {
                icon: <Award className="w-5 h-5" aria-hidden="true" />,
                title: 'Course Materials You Keep Access To',
                body: 'All 194 slides across the four days, in your own browser account, so you can review any chapter long after the live sessions end.',
              },
              {
                icon: <CheckCircle2 className="w-5 h-5" aria-hidden="true" />,
                title: 'Daily Evaluation and Mastery Check',
                body: 'Each day closes with a graded evaluation that teaches as it marks — every answer is explained — plus a mastery check built on scenarios you have not seen. 80% to pass, retakes allowed.',
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

          {/* First-offering-only note */}
          <div className="rounded-2xl bg-amber-500/10 border border-amber-500/30 p-5 mb-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" aria-hidden="true" />
            <div className="text-sm leading-relaxed">
              <div className="text-amber-200 font-semibold mb-1">First offering only</div>
              <p className="text-amber-100/90">
                The Founding Cohort discount of over 60% is available only for the first live offering.
                Future offerings will return to the regular{' '}
                {formatAmount(REGULAR_PRICE_CENTS, 'usd')} per-seat price.
              </p>
            </div>
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
              Founder of ProReadyEngineer. 19+ years in gas-turbine combustion with 1,000+
              mapping tests across flex-fuel operations, from 100% propane to hydrogen
              blending. Multiple patents in gas-turbine combustion and emissions reduction.
              Bassam has trained and mentored dozens of engineers, helping them understand
              complex combustion and mapping concepts with practical, real-world clarity.
              See reviews in the{' '}
              <Link to="/testimonials" className="text-cyan-400 hover:text-cyan-300 underline">
                Testimonials section
              </Link>
              {' '}on proreadyengineer.com.
            </p>
            <p className="text-slate-300 text-sm leading-relaxed">
              The course is built around field-grade decisions, not textbook theory. Every
              section answers "what would you do at 2 a.m. when the operator calls" rather
              than "what does the textbook say."
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
              No prior gas turbine knowledge required. You'll leave able to map similar
              systems end-to-end.
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
                        Founding Cohort seat —{' '}
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
                  href="mailto:info@proreadyengineer.com?subject=Waitlist — Gas Turbine Emissions Mapping"
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
                  placeholder="Lead Combustion Engineer"
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
                Secure · 15 seats per cohort · Auto-locks when full
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

export default GasTurbineEmissionsMapping;
