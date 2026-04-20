import React, { useEffect, useState } from 'react';
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
const COURSE_CAPACITY = 15;
const NEXT_COHORT_DATE = 'May 15, 2026';
const NOTEBOOKLM_URL =
  'https://notebooklm.google.com/notebook/39f245f9-bb92-4b02-9eee-4e37baa927ca/preview';

// Backend endpoints — Phase 2 will replace these with real Render API URLs
// TODO(Phase 2): set to https://proreadyengineer-training-api.onrender.com once deployed
const API_BASE = ''; // empty means "not wired yet" — form simulates success
const SEATS_ENDPOINT = API_BASE ? `${API_BASE}/api/seats` : '';
const REGISTER_ENDPOINT = API_BASE ? `${API_BASE}/api/register` : '';

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
  { code: 'D6', label: '+ 6th Circuit (flex-fuel)', color: 'bg-slate-700/80', text: 'text-slate-200' },
];

type Day = {
  n: number;
  title: string;
  summary: string;
  topics: string[];
  icon: React.ReactNode;
};

const CURRICULUM: Day[] = [
  {
    n: 1,
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
    n: 2,
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
    n: 3,
    title: 'DLE Operations & Emissions',
    summary:
      'Lean-premixed operating window, NOx/CO trade-off, CEMS, regulatory corrections.',
    topics: [
      'The DLE operating window φ ≈ 0.45–0.6',
      'Thermal-NOx exponential sensitivity to flame temperature',
      'CO surge near the lean limit',
      'CEMS calibration drift and regulatory corrections',
    ],
    icon: <Gauge className="w-6 h-6" />,
  },
  {
    n: 4,
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
    n: 5,
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
const GasTurbineEmissionsMapping = () => {
  const [seatsTaken, setSeatsTaken] = useState<number | null>(null);
  const [seatsLoading, setSeatsLoading] = useState(true);
  const [formState, setFormState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [formError, setFormError] = useState<string | null>(null);

  // Fetch live seat count. When API_BASE is empty we skip and show a conservative default.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!SEATS_ENDPOINT) {
        if (!cancelled) {
          setSeatsTaken(0); // Phase 1 placeholder — backend not wired yet
          setSeatsLoading(false);
        }
        return;
      }
      try {
        const res = await fetch(SEATS_ENDPOINT, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { taken: number };
        if (!cancelled) {
          setSeatsTaken(data.taken);
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
    seatsTaken === null ? COURSE_CAPACITY : Math.max(0, COURSE_CAPACITY - seatsTaken);
  const isFull = seatsTaken !== null && seatsTaken >= COURSE_CAPACITY;
  const progressPct =
    seatsTaken === null ? 0 : Math.min(100, (seatsTaken / COURSE_CAPACITY) * 100);

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
      const res = await fetch(REGISTER_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(Object.fromEntries(formData.entries())),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setFormError(data.error || `Registration failed (${res.status}).`);
        setFormState('error');
        return;
      }
      setSeatsTaken(data.taken ?? (seatsTaken ?? 0) + 1);
      setFormState('success');
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
            5-Day Expert Course · Next Cohort {NEXT_COHORT_DATE}
          </div>
          <h1 className="text-4xl md:text-6xl font-bold mb-4 leading-tight">
            Gas Turbine <span className="text-gradient">Emissions Mapping</span>
          </h1>
          <p className="text-2xl md:text-3xl font-light text-slate-300 mb-8">
            De-mystifying complexity — the gas turbine mapping expert course.
          </p>
          <p className="text-slate-400 text-lg max-w-3xl mb-10 leading-relaxed">
            Modern DLE combustion systems look daunting — six distinct gas circuits, bounded by
            narrow dynamics corridors and moving ambient targets. This course takes you from
            zero gas-turbine knowledge to confident field mapper over five days, taught by a
            practitioner with 17+ years of live mapping experience and multiple patents in the
            field.
          </p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat icon={<Clock className="w-5 h-5" />} label="Duration" value="5 Days" />
            <Stat
              icon={<Calendar className="w-5 h-5" />}
              label="Next Cohort"
              value={NEXT_COHORT_DATE}
            />
            <Stat
              icon={<Users className="w-5 h-5" />}
              label="Cohort Size"
              value={`${COURSE_CAPACITY} Seats`}
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
                Seat availability — {NEXT_COHORT_DATE} cohort
              </div>
              <div className="text-2xl font-bold">
                {seatsLoading ? (
                  <span className="text-slate-500">Loading…</span>
                ) : isFull ? (
                  <span className="text-amber-400">Cohort full — waitlist only</span>
                ) : (
                  <span>
                    {seatsRemaining} of {COURSE_CAPACITY} seats remaining
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
                  <div className="text-3xl font-bold text-white">φ ≈ 0.45 – 0.6</div>
                </div>
              </div>
            </div>

            <p className="text-slate-500 text-xs leading-relaxed">
              Bounded by LFD and crucial HFD limits. The skill is knowing which lever —
              pilot biasing, ELBO, T_flame trim — to pull when the corridor narrows on you.
            </p>
          </motion.div>
        </div>

        {/* CURRICULUM TIMELINE */}
        <div className="mb-16">
          <div className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-400 mb-2">
            Curriculum
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-8">5-Day Arc</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            {CURRICULUM.map((d, i) => (
              <motion.div
                key={d.n}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.05 }}
                className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800 hover:border-cyan-500/50 transition-all flex flex-col"
              >
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
                    {d.icon}
                  </div>
                  <div className="text-xs font-mono uppercase tracking-wider text-slate-500">
                    Day {d.n}
                  </div>
                </div>
                <h3 className="font-bold text-white mb-2 text-lg leading-tight">{d.title}</h3>
                <p className="text-slate-400 text-sm mb-4 leading-relaxed">{d.summary}</p>
                <ul className="space-y-2 mt-auto">
                  {d.topics.map((t) => (
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
            ))}
          </div>
        </div>

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
              Founder of ProReadyEngineer. 17+ years in gas-turbine combustion with 1,000+
              mapping tests across flex-fuel operations — 100 % propane through hydrogen
              blending. Multiple patents in combustion tuning and emissions reduction.
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
            Reserve your seat — {NEXT_COHORT_DATE} cohort
          </h2>
          <p className="text-slate-400 mb-8">
            {isFull
              ? `All ${COURSE_CAPACITY} seats are taken. Join the waitlist for the next cohort.`
              : `${seatsRemaining} of ${COURSE_CAPACITY} seats remaining.`}
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
          ) : isFull ? (
            <div className="text-center py-12">
              <div className="w-20 h-20 bg-amber-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <Lock className="w-10 h-10 text-amber-400" />
              </div>
              <h3 className="text-2xl font-bold mb-4">Cohort full</h3>
              <p className="text-slate-400 mb-8 max-w-md mx-auto">
                All 15 seats for the {NEXT_COHORT_DATE} cohort are taken. Email{' '}
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
                  label="Work Email"
                  name="email"
                  type="email"
                  required
                  placeholder="jane@company.com"
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
