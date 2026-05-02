import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Calendar,
  Users,
  Clock,
  Award,
  Flame,
  Activity,
  Gauge,
  Cloud,
  Wrench,
  CheckCircle2,
  Lock,
  MessageSquare,
  ExternalLink,
  Send,
  AlertTriangle,
} from 'lucide-react';

// -----------------------------------------------------------------------------
// Course constants
// -----------------------------------------------------------------------------
// Course code matches the backend Course.code. Start date + seats are now
// fetched from /api/courses/{code}; the constants below are fallbacks for
// local preview before the backend is reachable.
const COURSE_CODE = 'gas-turbine-emissions-mapping-2026-05';
const DEFAULT_CAPACITY = 15;
const DEFAULT_COHORT_DATE = 'May 15, 2026';
const NOTEBOOKLM_URL =
  'https://notebooklm.google.com/notebook/39f245f9-bb92-4b02-9eee-4e37baa927ca/preview';

// Backend endpoints. Set VITE_API_BASE in your deploy env to the Render URL,
// e.g. https://proreadyengineer-training-api.onrender.com
// When unset (local dev without backend), the form simulates success so the UI
// can be previewed without the API running.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';
const COURSE_ENDPOINT = API_BASE ? `${API_BASE}/api/courses/${COURSE_CODE}` : '';
const REGISTER_ENDPOINT = API_BASE ? `${API_BASE}/api/register` : '';

// Parse an ISO yyyy-mm-dd date into "May 15, 2026" without timezone drift.
const formatStartDate = (iso: string): string => {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  if (!y || !m || !d) return iso;
  const months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];
  return `${months[m - 1]} ${d}, ${y}`;
};

type Circuit = {
  code: string;
  label: string;
  color: string;
  text: string;
};

const CIRCUITS: Circuit[] = [
  { code: 'OM', label: 'Outer Main', color: 'bg-orange-500/80', text: 'text-orange-100' },
  { code: 'OP', label: 'Outer Pilot', color: 'bg-red-500/80', text: 'text-red-100' },
  { code: 'IM', label: 'Inner Main', color: 'bg-slate-400/80', text: 'text-slate-900' },
  { code: 'IP', label: 'Inner Pilot', color: 'bg-emerald-500/80', text: 'text-emerald-950' },
  { code: 'IE', label: 'Inner ELBO', color: 'bg-emerald-300/80', text: 'text-emerald-950' },
  { code: 'OE', label: 'Outer ELBO', color: 'bg-red-900/80', text: 'text-red-100' },
];

// Curriculum content. Index 0 -> Day 1, index 1 -> Day 2, etc.
// Dates are *not* stored here — they come from the live API (day_dates)
// so the admin can adjust them without a code change.
type Day = {
  title: string;
  summary: string;
  topics: string[];
  icon: React.ReactNode;
};

const CURRICULUM: Day[] = [
  {
    title: 'Fundamentals of Combustion',
    summary:
      'Flame types, GT cycles, premixed vs diffusion, burning velocity, equivalence ratio basics.',
    topics: [
      'Rapid exothermic oxidation framed for field engineers',
      'Premixed / non-premixed / partially-premixed classifications',
      'Burning velocity S_L and its role in flashback / LBO',
      'Equivalence ratio φ as master variable',
    ],
    icon: <Flame className="w-6 h-6" />,
  },
  {
    title: 'Combustion Dynamics',
    summary:
      'Thermoacoustics, LFD vs HFD, the Rayleigh criterion, sensors, mitigation levers.',
    topics: [
      'Low-Frequency Dynamics (LFD) 150–1000 Hz',
      'High-Frequency Dynamics (HFD) >1000 Hz (architecture-specific)',
      'Rayleigh criterion and pressure–heat-release phasing',
      'Mitigation: pilot biasing, ELBO, T_flame trim',
    ],
    icon: <Activity className="w-6 h-6" />,
  },
  {
    title: 'DLE Operations & Emissions',
    summary:
      'Lean-premixed operating window, NOx/CO trade-off, CEMS, regulatory corrections.',
    topics: [
      'Thermal-NOx exponential sensitivity to flame temperature',
      'CO surge near the lean limit',
      'CEMS calibration drift and regulatory corrections',
      'How to define the mapped conditions',
      'Learn hands on using the LMS100 interactive simulator',
    ],
    icon: <Gauge className="w-6 h-6" />,
  },
  {
    title: 'Mapping & Ambient Effects',
    summary:
      'Per-circuit fuel split optimisation, seasonal remapping, humidity and inlet T effects.',
    topics: [
      'Systematic sweep methodology for fuel splits',
      'Hotter inlet air → effectively richer mixture',
      'Humidity as an oxygen diluent',
      'Hardware degradation drivers for remapping',
    ],
    icon: <Cloud className="w-6 h-6" />,
  },
  {
    title: 'Flex Fuel & Troubleshooting',
    summary:
      'Hydrogen blending, Wobbe / Modified Wobbe Index, RCA for LBO, flashback, stage-down events.',
    topics: [
      'Propane → natural gas → hydrogen blends',
      'Wobbe Index and Modified Wobbe Index drift',
      'RCA workflow for stage-down events',
      'Acoustic + CO/NOx signatures before visible damage',
    ],
    icon: <Wrench className="w-6 h-6" />,
  },
];

// Placeholder rendered for days that exist in the admin schedule but go
// beyond the locally-defined curriculum content. Lets admins extend a
// course past 5 days without immediately needing a code change.
const TBD_DAY: Day = {
  title: 'Schedule TBD',
  summary: 'Detailed agenda for this day will be published soon.',
  topics: ['Topic outline pending'],
  icon: <Calendar className="w-6 h-6" />,
};

const STARTER_PROMPTS = [
  'My NOx is drifting up 5 ppm overnight at constant load — likely mapping-related root causes?',
  'Walk me through a systematic emissions mapping sweep on a dual-fuel DLE combustor.',
  'Explain how φ governs the operating envelope when ambient T3 deviates ±15 °C from design.',
];

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
const DEFAULT_DAY_DATES: string[] = [
  'May 16, 2026',
  'May 17, 2026',
  'May 23, 2026',
  'May 24, 2026',
  'May 30, 2026',
];

const GasTurbineEmissionsMapping = () => {
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
        };
        if (!cancelled) {
          setSeatsTaken(data.seats_taken);
          setCapacity(data.total_seats);
          setCohortDate(formatStartDate(data.start_date));
          setCourseStatus(data.status);
          if (Array.isArray(data.day_dates) && data.day_dates.length > 0) {
            setDayDates(data.day_dates.map(formatStartDate));
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
      setFormState(data.status === 'duplicate' ? 'duplicate' : 'success');
    } catch {
      setFormError('Network error. Please try again or email info@proreadyengineer.com.');
      setFormState('error');
    }
  };

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* HERO */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-16"
        >
          <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-4">
            {dayDates.length || CURRICULUM.length}-Day Expert Course · Next Cohort {cohortDate}
          </div>
          <h1 className="text-4xl md:text-6xl font-bold mb-6 leading-tight">
            Gas Turbine <span className="text-gradient">Emissions Mapping</span>
          </h1>

          <div className="flex flex-wrap items-center gap-4 mb-10">
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
              <Send className="w-4 h-4 ml-2 inline-block -mt-0.5" />
            </a>
            <span className="text-sm text-slate-500">
              No payment required to register — seat held as pending.
            </span>
          </div>

          {/* Course infographic — placed directly under the title, matching site pattern */}
          <div className="rounded-3xl overflow-hidden border border-slate-800 bg-slate-900/50 mb-10 shadow-2xl shadow-cyan-900/10">
            <img
              src="/Mapping_Training_Infographic_5.png"
              alt="Gas Turbine Emissions Mapping — De-mystifying Complexity: 6 gas circuits (OM, OP, OE, IM, IP, IE), the dynamics corridor (Φ ≈ 0.45–0.6), and 5-day course timeline"
              className="w-full h-auto block"
              loading="eager"
            />
          </div>

          <p className="text-2xl md:text-3xl font-light text-slate-300 mb-8">
            De-mystifying complexity — the gas turbine mapping expert course.
          </p>
          <p className="text-slate-400 text-lg mb-10 leading-relaxed">
            Modern DLE combustion systems look daunting — six distinct gas circuits, bounded by
            narrow dynamics corridors and moving ambient targets. This course takes you from
            zero gas-turbine knowledge to confident field mapper over five days, taught by a
            practitioner with 19+ years of live mapping experience and multiple patents in the
            field.
          </p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat
              icon={<Clock className="w-5 h-5" />}
              label="Duration"
              value={`${dayDates.length || CURRICULUM.length} Days`}
            />

            <Stat
              icon={<Calendar className="w-5 h-5" />}
              label="Next Cohort"
              value={cohortDate}
            />
            <Stat
              icon={<Users className="w-5 h-5" />}
              label="Cohort Size"
              value={`${capacity} Seats`}
            />
            <Stat icon={<Award className="w-5 h-5" />} label="Level" value="Beginner → Expert" />
          </div>
        </motion.div>

        {/* SEATS BAR */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mb-16 p-6 md:p-8 rounded-3xl bg-slate-900/50 border border-slate-800"
        >
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <div>
              <div className="text-xs font-mono uppercase tracking-wider text-slate-500 mb-1">
                Seat availability — {cohortDate} cohort
              </div>
              <div className="text-2xl font-bold">
                {seatsLoading ? (
                  <span className="text-slate-500">Loading…</span>
                ) : courseStatus === 'closed' ? (
                  <span className="text-amber-400">Registration closed</span>
                ) : atCapacity ? (
                  <span className="text-amber-400">Cohort full — waitlist only</span>
                ) : (
                  <span>
                    {seatsRemaining} of {capacity} seats remaining
                  </span>
                )}
              </div>
            </div>
            {isFull ? (
              <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-sm font-semibold">
                <Lock className="w-4 h-4" /> Registration closed
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
        </motion.div>

        {/* FLYER — Combustion system + Dynamics corridor */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-16">
          {/* Left: 6 circuits */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="p-8 rounded-3xl bg-slate-900/50 border border-slate-800"
          >
            <div className="text-xs font-mono uppercase tracking-wider text-amber-400 mb-2">
              The Complex Combustion System
            </div>
            <h3 className="text-2xl font-bold mb-4">6 distinct gas circuits</h3>
            <p className="text-slate-400 text-sm leading-relaxed mb-6">
              Modern DLE combustors route fuel through multiple independently-metered circuits.
              Each has its own response curve, its own instability signature, and its own role
              in the emissions / dynamics trade-off. Mastering them is the whole game.
            </p>
            <div className="space-y-3">
              {CIRCUITS.map((c) => (
                <div
                  key={c.code}
                  className="flex items-center gap-4 p-3 rounded-xl bg-slate-950/60 border border-slate-800"
                >
                  <span
                    className={`w-14 h-10 rounded-lg flex items-center justify-center font-mono font-bold text-sm ${c.color} ${c.text}`}
                  >
                    {c.code}
                  </span>
                  <span className="text-slate-300 text-sm">{c.label}</span>
                </div>
              ))}
            </div>
          </motion.div>

          {/* Right: Dynamics Corridor */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="p-8 rounded-3xl bg-slate-900/50 border border-slate-800"
          >
            <div className="text-xs font-mono uppercase tracking-wider text-cyan-400 mb-2">
              Master Dynamics Boundaries
            </div>
            <h3 className="text-2xl font-bold mb-4">The dynamics corridor</h3>
            <p className="text-slate-400 text-sm leading-relaxed mb-6">
              Every operating point lives inside a narrow corridor bounded above by{' '}
              <span className="text-amber-400 font-semibold">HFD limits</span> (NOx-rich side)
              and below by{' '}
              <span className="text-cyan-400 font-semibold">LFD limits</span> (CO + lean-blowout
              side). You'll learn to map <em>logic</em>, not recipes.
            </p>

            {/* Dynamics corridor schematic */}
            <div className="relative h-40 rounded-2xl bg-gradient-to-b from-amber-500/10 via-cyan-500/10 to-cyan-500/10 border border-slate-800 overflow-hidden mb-4">
              <div className="absolute inset-x-0 top-0 h-px bg-amber-500/60"></div>
              <div className="absolute inset-x-0 bottom-0 h-px bg-cyan-500/60"></div>
              <div className="absolute top-2 left-3 text-[10px] font-mono text-amber-400">
                HFD LIMIT — NOx (rich)
              </div>
              <div className="absolute bottom-2 left-3 text-[10px] font-mono text-cyan-400">
                LFD LIMIT — CO + LBO (lean)
              </div>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <div className="text-xs font-mono text-slate-400 mb-1">DLE operating window</div>
                  <div className="text-3xl font-bold text-white">φ ≈ Min – Max</div>
                </div>
              </div>
            </div>

            <p className="text-slate-500 text-xs leading-relaxed">
              Bounded by LFD and crucial HFD limits. The skill is knowing which lever —
              pilot biasing, ELBO, T_flame trim — to pull when the corridor narrows on you.
            </p>
          </motion.div>
        </div>

        {/* CURRICULUM TIMELINE — number of cards is driven by the admin's */}
        {/* day_dates list. Topics for each day come from the local CURRICULUM */}
        {/* array; days beyond CURRICULUM.length render as a TBD placeholder. */}
        <div className="mb-16">
          <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-2">
            Curriculum
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-8">
            {dayDates.length || CURRICULUM.length}-Day Arc
          </h2>
          <div
            className={`grid grid-cols-1 md:grid-cols-2 gap-4 ${
              (dayDates.length || CURRICULUM.length) <= 5
                ? 'lg:grid-cols-5'
                : 'lg:grid-cols-3'
            }`}
          >
            {(dayDates.length > 0 ? dayDates : DEFAULT_DAY_DATES).map((dateLabel, i) => {
              const day = CURRICULUM[i] ?? TBD_DAY;
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: i * 0.05 }}
                  className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800 hover:border-cyan-500/50 transition-all flex flex-col"
                >
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
                      {day.icon}
                    </div>
                    <div className="leading-tight">
                      <div className="text-xs font-mono uppercase tracking-wider text-slate-500">
                        Day {i + 1}
                      </div>
                      <div className="text-xs text-cyan-400 font-medium">{dateLabel}</div>
                    </div>
                  </div>
                  <h3 className="font-bold text-white mb-2 text-lg leading-tight">{day.title}</h3>
                  <p className="text-slate-400 text-sm mb-4 leading-relaxed">{day.summary}</p>
                  <ul className="space-y-2 mt-auto">
                    {day.topics.map((t) => (
                      <li
                        key={t}
                        className="text-xs text-slate-500 flex gap-2 leading-relaxed"
                      >
                        <CheckCircle2 className="w-3 h-3 text-cyan-500/70 shrink-0 mt-0.5" />
                        <span>{t}</span>
                      </li>
                    ))}
                  </ul>
                </motion.div>
              );
            })}
          </div>
        </div>

        {/* DAILY SCHEDULE — applies to every cohort day. Times are fixed (no */}
        {/* DST drift handling): the course runs in May 2026 when North */}
        {/* America is on DST, while Algeria + Saudi Arabia are DST-free. */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="mb-16"
        >
          <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-2">
            Daily schedule
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-3">Same hours every day</h2>
          <p className="text-slate-400 text-base mb-8 max-w-2xl leading-relaxed">
            Five teaching hours with a 10-minute break between each — keeping focus high
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
                className="p-5 rounded-2xl bg-slate-900/50 border border-slate-800 hover:border-cyan-500/50 transition-colors"
              >
                <div className="text-xs font-mono uppercase tracking-wider text-slate-500 mb-1">
                  {tz.label}
                </div>
                <div className="text-base font-semibold text-cyan-400 mb-3">{tz.city}</div>
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="text-xl font-bold text-white tabular-nums">{tz.start}</span>
                  <span className="text-slate-600">→</span>
                  <span className="text-xl font-bold text-white tabular-nums">{tz.end}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Hour-by-hour ruler — anchored to Eastern Time so it stays compact */}
          <div className="rounded-2xl bg-slate-900/50 border border-slate-800 p-5">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div className="text-xs font-mono uppercase tracking-wider text-slate-500">
                Hour-by-hour · Eastern Time
              </div>
              <div className="text-[11px] text-slate-500">10-minute break between hours</div>
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
                  <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500 shrink-0">
                    Hr {n}
                  </span>
                  <span className="text-slate-200 font-mono tabular-nums text-xs">{time}</span>
                </div>
              ))}
            </div>
          </div>
        </motion.div>

        {/* PRICING — Founding Cohort offer for the first live cohort */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="mb-16"
        >
          <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-2">
            Pricing
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-3">Founding Cohort Pricing</h2>
          <p className="text-slate-400 text-base mb-8 max-w-2xl leading-relaxed">
            For the first live offering, this advanced training is available at a special
            Founding Cohort price.
          </p>

          {/* Price hero */}
          <div className="rounded-3xl bg-gradient-to-br from-cyan-900/20 via-slate-900/60 to-blue-900/20 border border-cyan-500/30 p-8 md:p-10 mb-8">
            <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
              <div>
                <div className="text-xs font-mono uppercase tracking-wider text-cyan-300 mb-2">
                  Founding cohort · per seat
                </div>
                <div className="flex items-baseline gap-3 flex-wrap">
                  <span className="text-5xl md:text-6xl font-bold text-white tabular-nums">
                    $1,000
                  </span>
                  <div className="flex flex-col text-sm">
                    <span className="text-slate-500 line-through tabular-nums">$3,000</span>
                    <span className="text-slate-500">regular future price</span>
                  </div>
                </div>
              </div>
              <a href="#register" className="btn-primary text-base px-8 py-4 self-start md:self-auto">
                Reserve my seat
                <Send className="w-4 h-4 ml-2 inline-block -mt-0.5" />
              </a>
            </div>
          </div>

          {/* Value framing */}
          <div className="space-y-4 text-slate-300 leading-relaxed mb-10 max-w-3xl">
            <p>
              Your seat includes live instructor-led training, AI-based gas turbine engine
              simulator access, course materials, and the opportunity to ask your questions
              directly during the live sessions.
            </p>
            <p>
              This course is designed to help you understand the real logic behind gas turbine
              emissions mapping — including fuel splits, NOx, CO, combustion dynamics, safe
              operating windows, and practical mapping decisions.
            </p>
            <p className="text-slate-400">
              You are not just attending a class. You are building practical mapping
              understanding through expert instruction, realistic simulator-based learning,
              and direct interaction with the instructor.
            </p>
          </div>

          {/* Included grid */}
          <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-4">
            Included with your seat
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {[
              {
                icon: <Users className="w-5 h-5" />,
                title: 'Live training with Bassam Abdelnabi',
                body: 'Learn directly from an instructor with deep real-world gas turbine combustion and mapping experience.',
              },
              {
                icon: <MessageSquare className="w-5 h-5" />,
                title: 'Direct Q&A during the course',
                body: 'Ask your specific questions during the live sessions and connect the training concepts to real field situations.',
              },
              {
                icon: <Activity className="w-5 h-5" />,
                title: 'AI-based engine simulator access',
                body: 'Use an interactive simulator to make the mapping process more practical, visual, and realistic.',
              },
              {
                icon: <Award className="w-5 h-5" />,
                title: 'Course materials and reference content',
                body: 'Receive access to the course content so you can review the concepts after the live sessions.',
              },
              {
                icon: <Wrench className="w-5 h-5" />,
                title: 'Practical mapping examples',
                body: 'Work through examples that connect fuel splits, emissions behavior, dynamics, operability, and safe mapping decisions.',
              },
            ].map((item) => (
              <div
                key={item.title}
                className="p-5 rounded-2xl bg-slate-900/50 border border-slate-800 hover:border-cyan-500/50 transition-colors flex flex-col"
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-9 h-9 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shrink-0">
                    {item.icon}
                  </div>
                  <h3 className="font-semibold text-white text-sm leading-tight">{item.title}</h3>
                </div>
                <p className="text-slate-400 text-sm leading-relaxed">{item.body}</p>
              </div>
            ))}
          </div>

          {/* First-offering-only note */}
          <div className="rounded-2xl bg-amber-500/10 border border-amber-500/30 p-5 mb-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            <div className="text-sm leading-relaxed">
              <div className="text-amber-200 font-semibold mb-1">First offering only</div>
              <p className="text-amber-100/90">
                The $1,000 Founding Cohort price is available only for the first live offering.
                Future offerings are expected to return to the regular $3,000 per seat price.
              </p>
            </div>
          </div>

          {/* Groups */}
          <p className="text-slate-500 text-sm leading-relaxed">
            For teams enrolling multiple engineers,{' '}
            <Link to="/contact" className="text-cyan-400 hover:text-cyan-300 underline">
              contact ProReadyEngineer
            </Link>{' '}
            for group registration options.
          </p>
        </motion.div>

        {/* NOTEBOOKLM INTERACTIVE DEMO */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="mb-16 p-8 md:p-12 rounded-[2.5rem] bg-gradient-to-br from-cyan-900/20 via-slate-900/40 to-blue-900/20 border border-cyan-500/20"
        >
          <div className="flex items-center gap-3 mb-4">
            <MessageSquare className="w-6 h-6 text-cyan-400" />
            <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400">
              Try before you enrol
            </div>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            Ask the course brain anything.
          </h2>
          <p className="text-slate-300 text-lg max-w-3xl mb-8 leading-relaxed">
            The full training material is indexed in an interactive notebook. Ask any question
            about DLE mapping, flame dynamics, emissions tuning, or field RCA — you'll get an
            answer pulled directly from the source material, with chapter citations. If the
            answer is shallow, the course won't be a fit. If it cites the right chapters, you'll
            know.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-8">
            {STARTER_PROMPTS.map((p) => (
              <div
                key={p}
                className="p-4 rounded-xl bg-slate-950/50 border border-slate-800 text-sm text-slate-300 leading-relaxed"
              >
                <span className="text-cyan-400 font-mono text-xs mr-2">Try:</span>"{p}"
              </div>
            ))}
          </div>

          <a
            href={NOTEBOOKLM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 btn-primary"
          >
            Open the interactive demo <ExternalLink className="w-4 h-4" />
          </a>
          <p className="text-xs text-slate-500 mt-3">
            Opens in a new tab. Source-grounded answers with citations. No sign-up required.
          </p>
        </motion.div>

        {/* INSTRUCTOR */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-16">
          <div className="lg:col-span-2 p-8 rounded-3xl bg-slate-900/50 border border-slate-800">
            <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-2">
              Led By
            </div>
            <h2 className="text-3xl font-bold mb-4">Bassam Abdelnabi</h2>
            <p className="text-slate-300 leading-relaxed mb-4">
              Founder of ProReadyEngineer. 19+ years in gas-turbine combustion with 1,000+
              mapping tests across flex-fuel operations — from 100% propane to hydrogen
              blending. Multiple patents in gas-turbine combustion and emissions reduction.
              Bassam has trained and mentored dozens of engineers, helping them understand
              complex combustion and mapping concepts with practical, real-world clarity.
              See reviews in the{' '}
              <Link to="/testimonials" className="text-cyan-400 hover:text-cyan-300 underline">
                Testimonials section
              </Link>
              {' '}on proreadyengineer.com.
            </p>
            <p className="text-slate-400 text-sm leading-relaxed">
              The course is built around field-grade decisions, not textbook theory. Every
              section answers "what would you do at 2 a.m. when the operator calls" rather
              than "what does the textbook say."
            </p>
          </div>
          <div className="p-8 rounded-3xl bg-slate-900/50 border border-slate-800">
            <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-4">
              Ideal For
            </div>
            <ul className="space-y-3">
              {IDEAL_FOR.map((x) => (
                <li key={x} className="flex items-center gap-3 text-slate-300">
                  <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span>{x}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-slate-500 mt-6 leading-relaxed">
              No prior gas turbine knowledge required. You'll leave able to map similar
              systems end-to-end.
            </p>
          </div>
        </div>

        {/* REGISTRATION FORM */}
        <motion.div
          id="register"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="p-8 md:p-12 rounded-[2.5rem] bg-slate-900/50 border border-slate-800 backdrop-blur-sm"
        >
          <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-2">
            Register
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-2">
            Reserve your seat — {cohortDate} cohort
          </h2>
          <p className="text-slate-400 mb-8">
            {courseStatus === 'closed'
              ? 'Registration is closed for this cohort.'
              : atCapacity
                ? `All ${capacity} seats are taken. Join the waitlist for the next cohort.`
                : `${seatsRemaining} of ${capacity} seats remaining.`}
          </p>

          {formState === 'success' ? (
            <div className="text-center py-12">
              <div className="w-20 h-20 bg-cyan-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <CheckCircle2 className="w-10 h-10 text-cyan-400" />
              </div>
              <h3 className="text-2xl font-bold mb-4">Registration received</h3>
              <p className="text-slate-400 mb-8 max-w-md mx-auto">
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
            </div>
          ) : formState === 'duplicate' ? (
            <div className="text-center py-12">
              <div className="w-20 h-20 bg-cyan-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <CheckCircle2 className="w-10 h-10 text-cyan-400" />
              </div>
              <h3 className="text-2xl font-bold mb-4">You're already registered</h3>
              <p className="text-slate-400 mb-8 max-w-md mx-auto">
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
                <Lock className="w-10 h-10 text-amber-400" />
              </div>
              <h3 className="text-2xl font-bold mb-4">
                {courseStatus === 'closed' ? 'Registration closed' : 'Cohort full'}
              </h3>
              <p className="text-slate-400 mb-8 max-w-md mx-auto">
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
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
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
                  <label className="text-xs font-medium text-slate-400 uppercase tracking-wider ml-1">
                    Years of Experience
                  </label>
                  <select
                    name="years_experience"
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors text-slate-200"
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

              <label className="flex items-start gap-3 text-xs text-slate-500 leading-relaxed">
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
                <Send className="w-4 h-4" />
              </button>

              <p className="text-[10px] text-slate-600 text-center uppercase tracking-widest">
                Secure · 15 seats per cohort · Auto-locks when full
              </p>
            </form>
          )}
        </motion.div>
      </div>
    </div>
  );
};

// -----------------------------------------------------------------------------
// Small helpers
// -----------------------------------------------------------------------------
const Stat = ({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) => (
  <div className="p-4 rounded-2xl bg-slate-900/50 border border-slate-800">
    <div className="flex items-center gap-2 text-cyan-400 mb-2">{icon}</div>
    <div className="text-xs font-mono uppercase tracking-wider text-slate-500 mb-1">
      {label}
    </div>
    <div className="text-sm font-bold text-white">{value}</div>
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
    <label className="text-xs font-medium text-slate-400 uppercase tracking-wider ml-1">
      {label}
    </label>
    <input
      name={name}
      type={type}
      required={required}
      placeholder={placeholder}
      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors"
    />
  </div>
);

export default GasTurbineEmissionsMapping;
