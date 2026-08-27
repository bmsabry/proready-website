import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Calendar,
  Clock,
  Users,
  BookOpen,
  ArrowRight,
  Award,
  FlaskConical,
  MessagesSquare,
  Infinity as InfinityIcon,
  PlayCircle,
  Layers,
  Tag,
} from 'lucide-react';
import { Reveal, SectionHeading, CTABand, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';
import {
  courseSnapshot,
  formatIsoDate as formatStartDate,
  snapshotStartLabel,
} from '../data/courseSnapshot';

// Courses backed by the registration API expose a `code` so the card can show
// live seats / start date instead of hardcoded values.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

// formatStartDate ("2026-08-29" -> "August 29, 2026", no timezone drift) is
// imported above from data/courseSnapshot, so the build-time snapshot and the
// runtime fetch format dates identically.

// The flagship's course code, needed before `courses` is declared because its
// prerender fallbacks are read from the build-time snapshot.
const FLAGSHIP_CODE = 'gas-turbine-emissions-mapping-2026-05';
const FLAGSHIP_SNAPSHOT = courseSnapshot(FLAGSHIP_CODE);

const courses = [
  {
    id: 1,
    title: "Gas Turbine Emissions Mapping",
    category: "Thermal Fluids",
    // Duration, seats and date are prerender fallbacks. They are what crawlers
    // and no-JS visitors read, so they are taken from the build-time snapshot
    // of the live course record rather than typed here — a typed value goes
    // stale the moment the admin moves the cohort. See data/courseSnapshot.
    duration: FLAGSHIP_SNAPSHOT?.dayDates.length
      ? `${FLAGSHIP_SNAPSHOT.dayDates.length} Days`
      : "4 Days",
    level: "Beginner to Expert",
    attendees: FLAGSHIP_SNAPSHOT?.totalSeats
      ? `${FLAGSHIP_SNAPSHOT.totalSeats} Seats`
      : "15 Seats",
    description: "De-mystify DLE combustion. Master the dynamics corridor, emissions mapping strategy, and flex-fuel troubleshooting from first principles to expert level. No prior gas turbine knowledge required.",
    nextDate: snapshotStartLabel(FLAGSHIP_CODE, "August 29, 2026"),
    slug: "gas-turbine-emissions-mapping",
    code: FLAGSHIP_CODE,
    featured: true
  },
];

type LiveCourseInfo = {
  seatsRemaining: number;
  totalSeats: number;
  startDate: string; // already formatted "May 16, 2026"
  status: 'open' | 'closed';
  numDays: number; // length of day_dates; 0 if not scheduled
  priceCents: number; // 0 = invoice-only, no public price shown
  currency: string;
  recordedProductCode: string | null; // set when an on-demand edition exists
};

const WHY_TRAIN = [
  {
    icon: <Award className="w-6 h-6" aria-hidden="true" />,
    title: 'Practitioners, Not Lecturers',
    body: 'Taught by the engineers who design, test, and troubleshoot these systems: ex-GE, PhD-led, with patents in the field.',
  },
  {
    icon: <FlaskConical className="w-6 h-6" aria-hidden="true" />,
    title: 'Real Test-Cell Data & Field Experience',
    body: 'Lessons built on thousands of live mapping tests and real field events, not idealized textbook cases.',
  },
  {
    icon: <MessagesSquare className="w-6 h-6" aria-hidden="true" />,
    title: 'Small Cohorts, Direct Q&A',
    body: 'Limited seats keep every session interactive. Bring your hardest questions straight to the instructor.',
  },
];


/* ---------------- Upcoming catalog (waitlist) ----------------
   Seven programs in development, built from real course material.
   Grouped in two tracks; each card captures interest via /api/interest. */

type UpcomingCourse = {
  slug: string;
  title: string;
  pitch: string;
  audience: string;
  learn: string[];
  outline: string[];
};

type Track = { name: string; intro: string; courses: UpcomingCourse[] };

const TRACKS: Track[] = [
  {
    name: 'Rotating Equipment Series',
    intro:
      'Four courses that build on each other: start with pumps, add compressors, then go deep on the seals and valves that keep both running.',
    courses: [
      {
        slug: 'pumps',
        title: 'Pump Selection, Operation and Troubleshooting',
        pitch:
          'Every major pump type, its curves, its failure modes, and how to select, install, and troubleshoot it.',
        audience: 'Plant, process, operations, and maintenance engineers who specify or run pumps.',
        learn: [
          'Map the full pump family tree and shortlist the right type for a service',
          'Choose between centrifugal and positive displacement using flow, pressure, viscosity, and solids criteria',
          'Read performance curves (head, capacity, power, efficiency) and predict behavior off the design point',
          'Recognize, predict, and prevent cavitation',
          'Install pumps properly and lay out pumping stations',
          'Troubleshoot common pump problems and structure the maintenance response',
        ],
        outline: [
          'Pump families and how to choose',
          'Terminology, curves, and basic theory',
          'Construction and materials',
          'Cavitation',
          'Installation and pumping station design',
          'Troubleshooting and maintenance',
        ],
      },
      {
        slug: 'compressors',
        title: 'Compressor Selection, Operation and Troubleshooting',
        pitch:
          'Reciprocating, rotary, and centrifugal compressors: how they work, how they fail, and how to select the right one.',
        audience:
          'Plant and process engineers in gas processing, refining, petrochemical, and utilities.',
        learn: [
          'Compression fundamentals and the compressor family map',
          'Rotary positive displacement machines and where they fit',
          'Reciprocating compressors in depth: construction, operation, and capacity control',
          'Maintenance and troubleshooting of reciprocating machines',
          'Dynamic compressor behavior, performance, and operating limits',
          'A structured selection method for matching compressor type to service',
        ],
        outline: [
          'Introduction and compression basics',
          'Rotary positive displacement compressors',
          'Reciprocating compressors: design, operation, troubleshooting',
          'Turbocompressors',
          'Compressor seals',
          'Compressor selection',
        ],
      },
      {
        slug: 'mechanical-seals',
        title: 'Mechanical Seals',
        pitch:
          'From packing and lip seals to dry gas seals: select, install, and troubleshoot the seals that keep rotating machines running.',
        audience:
          'Rotating equipment, maintenance, and reliability engineers who own pumps and compressors.',
        learn: [
          'Classify seal families and pick the right one for a duty',
          'Read a mechanical seal assembly: pusher and metal-bellows designs',
          'Select seal support piping plans for flush, quench, and barrier service',
          'Understand dry gas seals on process compressors, with field case studies',
          'Install and commission seals to avoid early failure',
          'Diagnose seal failures from the evidence and apply proven corrections',
        ],
        outline: [
          'Sealing fundamentals and seal families',
          'Packing and mechanical seals',
          'Seal support systems and piping plans',
          'Dry gas seals and case studies',
          'Installation and operation',
          'Troubleshooting, failure causes and corrections',
        ],
      },
      {
        slug: 'valves',
        title: 'Valve Selection, Operation and Overpressure Protection',
        pitch:
          'Valve types, actuators, and code-compliant overpressure protection, from API practice down to installation and maintenance.',
        audience:
          'Plant, piping, and process engineers responsible for relief devices and valve integrity.',
        learn: [
          'Classify valves by function and construction, and match type to application',
          'Specify valve actuators and their selection considerations',
          'Apply ASME and API overpressure protection requirements: MAWP, accumulation, set pressure, blowdown',
          'Select among spring-loaded, balanced bellows, and pilot-operated relief valves',
          'Apply pressure sustaining valves in liquid systems',
          'Install and maintain valves for long service life',
        ],
        outline: [
          'Valve fundamentals, classification and application',
          'Valve actuators',
          'Pressure relief valves',
          'Safety valves',
          'Pressure sustaining valves',
          'Installation and maintenance',
        ],
      },
    ],
  },
  {
    name: 'Gas Turbine & Digitalization Series',
    intro:
      'A clean arc across three courses: design the combustor, test and evaluate it, then monitor the whole engine in service with a digital twin.',
    courses: [
      {
        slug: 'gt-combustor-design',
        title: 'Gas Turbine Combustor Design',
        pitch:
          'Size a combustor and design its diffuser, swirler, fuel injection, and cooling, using the Lefebvre method end to end.',
        audience:
          'Gas turbine, propulsion, and energy engineers who design, modify, or evaluate combustors.',
        learn: [
          'Compare can, turboannular, and annular architectures and state full design requirements',
          'Size the casing and liner and distribute air among primary, intermediate, and dilution zones',
          'Design the diffuser, air swirler, and primary-zone aerodynamics that anchor the flame',
          'Select and size fuel injection, accounting for spray evaporation and fuel properties',
          'Calculate liner heat transfer and design film cooling within a metal temperature budget',
          'Predict performance and emissions, carrying a complete design through a working workbook',
        ],
        outline: [
          'Architecture, requirements, and preliminary sizing',
          'Diffuser design and air distribution',
          'Swirler aerodynamics and flame stabilization',
          'Fuel injection and spray evaporation',
          'Liner heat transfer and cooling',
          'Dilution zone, performance, and emissions',
        ],
      },
      {
        slug: 'combustion-testing-evaluation',
        title: 'Combustion Systems Testing and Evaluation',
        pitch:
          'Measure what actually happens in a combustor: laser diagnostics, spray characterization, emissions, and disciplined test cell practice.',
        audience:
          'Test engineers, combustion R&D engineers, and lab leads who run or interpret rig tests.',
        learn: [
          'Choose the right measurement for the job, and know when optical diagnostics are worth the cost',
          'Set up and run laser Doppler anemometry: fringe model, seeding, signal processing',
          'Characterize sprays with phase Doppler: droplet size and velocity distributions, error sources',
          'Visualize flows with shadowgraphy and PIV, including image processing',
          'Instrument a combustion test: emissions sampling, gas analysis probes, and data acquisition',
          'Plan, execute, and report a complete test campaign',
        ],
        outline: [
          'Measurement fundamentals, turbulence, and uncertainty',
          'Point velocimetry: LDA principles and practice',
          'Spray and particle characterization',
          'Flow imaging: shadowgraphy, PIV, image processing',
          'Combustion test cell practice: emissions, probes, DAQ',
          'Planning, running, and reporting a campaign',
        ],
      },
      {
        slug: 'digital-twin',
        title: 'Building a Digital Twin',
        pitch:
          'Build a working gas turbine digital twin from plant data: physics core, health tracking, wash economics, early warning.',
        audience:
          'Performance, asset management, and digitalization engineers building a condition-monitoring twin.',
        learn: [
          'What a digital twin actually is and the one idea the whole system rests on',
          'Prepare real plant historian data and fix what is wrong with it before modelling',
          'Validate instruments first: tell a lying sensor from a failing machine',
          'Build a thermodynamic model of a specific engine without OEM data',
          'Track unit condition through health parameters, and know when the system should not trust itself',
          'Ship capabilities in order: degradation and wash economics, early warning, then diagnosis',
        ],
        outline: [
          'The twin concept and architecture',
          'Plant data and trusting the instruments',
          'The physics core: modelling without OEM data',
          'Health parameter estimation and uncertainty',
          'Degradation, wash economics, early warning, diagnosis',
          'Life accounting and fleet decisions',
        ],
      },
    ],
  },
];

/* ---------- Waitlist capture for an upcoming course ---------- */
const WaitlistForm = ({ slug }: { slug: string }) => {
  const [email, setEmail] = useState('');
  const [website, setWebsite] = useState(''); // honeypot
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>('idle');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setState('error');
      return;
    }
    setState('busy');
    try {
      const res = await fetch(`${API_BASE}/api/interest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course_slug: slug, email: email.trim(), website }),
      });
      setState(res.ok ? 'done' : 'error');
    } catch {
      setState('error');
    }
  };

  if (state === 'done') {
    return (
      <p className="text-sm text-cyan-300 mt-auto pt-2">
        You're on the list. We'll email you when this course opens.
      </p>
    );
  }
  return (
    <form onSubmit={submit} className="mt-auto pt-2 flex gap-2">
      <label className="sr-only" htmlFor={`wl-${slug}`}>
        Email for the {slug} waitlist
      </label>
      <input
        id={`wl-${slug}`}
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@company.com"
        className="flex-1 min-w-0 bg-slate-900/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-400 transition-colors"
      />
      <input
        type="text"
        value={website}
        onChange={(e) => setWebsite(e.target.value)}
        className="hidden"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
      />
      <button type="submit" disabled={state === 'busy'} className="btn-secondary px-4 py-2 text-sm whitespace-nowrap disabled:opacity-60">
        {state === 'busy' ? 'Adding…' : 'Notify me'}
      </button>
      {state === 'error' && (
        <span className="sr-only" role="alert">Could not join the waitlist, please retry.</span>
      )}
    </form>
  );
};

const UpcomingCard = ({ course, index }: { course: UpcomingCourse; index: number }) => (
  <Reveal delay={(index % 2) * 0.07} className="h-full">
    <div className="card card-hover p-7 h-full flex flex-col">
      <h3 className="text-lg font-bold mb-2 leading-snug">{course.title}</h3>
      <p className="text-slate-300 text-sm leading-relaxed mb-3">{course.pitch}</p>
      <p className="text-xs text-slate-400 mb-4">
        <span className="text-slate-300 font-medium">For:</span> {course.audience}
      </p>
      <details className="group mb-5">
        <summary className="cursor-pointer list-none inline-flex items-center gap-2 text-cyan-400 text-sm font-medium hover:text-cyan-300 transition-colors">
          <BookOpen className="w-4 h-4" aria-hidden="true" />
          What you'll learn
          <span className="text-slate-500 group-open:hidden">+</span>
          <span className="text-slate-500 hidden group-open:inline">−</span>
        </summary>
        <div className="mt-4 grid gap-6 md:grid-cols-2">
          <ul className="space-y-2">
            {course.learn.map((t) => (
              <li key={t} className="flex gap-2.5 text-sm text-slate-300 leading-relaxed">
                <span className="text-cyan-400 mt-0.5" aria-hidden="true">›</span>
                {t}
              </li>
            ))}
          </ul>
          <div>
            <p className="text-xs font-mono uppercase tracking-widest text-slate-400 mb-2">Outline</p>
            <ol className="space-y-1.5">
              {course.outline.map((m, i) => (
                <li key={m} className="text-sm text-slate-300">
                  <span className="font-mono text-xs text-slate-500 mr-2">{String(i + 1).padStart(2, '0')}</span>
                  {m}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </details>
      <WaitlistForm slug={course.slug} />
    </div>
  </Reveal>
);

const Training = () => {
  usePageMeta(
    'Professional Training',
    'Gas turbine, combustion, rotating equipment, and digital twin training taught by the engineers who design and test these systems. Live cohorts, on-demand programs, and a growing catalog: pumps, compressors, mechanical seals, valves, combustor design, combustion testing, digital twins.',
  );

  const [liveByCode, setLiveByCode] = useState<Record<string, LiveCourseInfo>>({});

  // Fetch live course data for any course that has a `code`. Falls back
  // silently to the hardcoded values when the API is unreachable.
  useEffect(() => {
    if (!API_BASE) return;
    let cancelled = false;
    const codes = courses.map((c) => c.code).filter((c): c is string => Boolean(c));
    (async () => {
      const entries = await Promise.all(
        codes.map(async (code) => {
          try {
            const res = await fetch(`${API_BASE}/api/courses/${code}`, { cache: 'no-store' });
            if (!res.ok) return null;
            const data = (await res.json()) as {
              start_date: string;
              total_seats: number;
              seats_taken: number;
              status: 'open' | 'closed';
              day_dates?: string[];
              price_cents?: number;
              currency?: string;
              recorded_product_code?: string | null;
            };
            // Prefer day_dates[0] over start_date so the listing matches
            // the detail page when admin updates the daily schedule.
            const startIso =
              Array.isArray(data.day_dates) && data.day_dates.length > 0
                ? data.day_dates[0]
                : data.start_date;
            const info: LiveCourseInfo = {
              seatsRemaining: Math.max(0, data.total_seats - data.seats_taken),
              totalSeats: data.total_seats,
              startDate: formatStartDate(startIso),
              status: data.status,
              numDays: Array.isArray(data.day_dates) ? data.day_dates.length : 0,
              priceCents: typeof data.price_cents === 'number' ? data.price_cents : 0,
              currency: data.currency || 'usd',
              recordedProductCode: data.recorded_product_code || null,
            };
            return [code, info] as const;
          } catch {
            return null;
          }
        }),
      );
      if (cancelled) return;
      const map: Record<string, LiveCourseInfo> = {};
      for (const e of entries) if (e) map[e[0]] = e[1];
      setLiveByCode(map);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const flagship = courses.find((c) => c.featured)!;

  const flagshipLive = flagship.code ? liveByCode[flagship.code] : undefined;
  const flagshipSeatsLabel = flagshipLive
    ? flagshipLive.status === 'closed'
      ? 'Registration closed'
      : flagshipLive.seatsRemaining === 0
        ? `Cohort full (${flagshipLive.totalSeats} seats)`
        : `${flagshipLive.seatsRemaining} of ${flagshipLive.totalSeats} seats left`
    : flagship.attendees;
  const flagshipDateLabel = flagshipLive ? flagshipLive.startDate : flagship.nextDate;
  // Price shows only when the API reports one; the SSR fallback stays priceless.
  const flagshipPriceLabel =
    flagshipLive && flagshipLive.priceCents > 0
      ? new Intl.NumberFormat('en-US', {
          style: 'currency',
          currency: flagshipLive.currency.toUpperCase(),
          minimumFractionDigits: flagshipLive.priceCents % 100 === 0 ? 0 : 2,
        }).format(flagshipLive.priceCents / 100)
      : null;
  const flagshipDurationLabel =
    flagshipLive && flagshipLive.numDays > 0 ? `${flagshipLive.numDays} Days` : flagship.duration;

  return (
    <div className="pb-4">
      <PageHero
        eyebrow="Professional Training"
        title={
          <>
            Train With the Engineers Who{' '}
            <span className="text-gradient">Build These Systems</span>
          </>
        }
        subtitle="Specialized courses taught by the engineers who design and test gas turbines, combustion systems, and industrial AI. Ex-GE, PhD-led, field-proven."
      />

      {/* WHY TRAIN WITH US */}
      <section className="pt-2 pb-16">
        <div className="container-site">
          <SectionHeading
            eyebrow="Why Train With Us"
            title="Field-Grade Knowledge, Transferred Directly"
            subtitle="Every course below is built around the decisions you actually face in the test cell and the field, not slides recycled from a textbook."
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {WHY_TRAIN.map((item, i) => (
              <Reveal key={item.title} delay={i * 0.08}>
                <div className="card card-hover p-8 h-full">
                  <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-5">
                    {item.icon}
                  </div>
                  <h3 className="text-lg font-bold mb-3">{item.title}</h3>
                  <p className="text-slate-300 text-sm leading-relaxed">{item.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* AVAILABLE NOW */}
      <section className="pb-8">
        <div className="container-site">
          <SectionHeading
            eyebrow="Available Now"
            title="Open for Enrollment"
            subtitle="A live cohort you can join today and a self-paced program you can start tonight."
          />
        </div>
      </section>
      <section className="container-site pb-8">
        <Reveal>
          <div className="relative card overflow-hidden p-8 md:p-12">
            <div
              className="absolute -top-32 -right-24 w-96 h-96 bg-cyan-500/10 blur-[120px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-10 items-center relative">
              <div className="lg:col-span-3">
                <div className="flex flex-wrap items-center gap-3 mb-5">
                  <span className="eyebrow">Flagship Course</span>
                  <span className="text-[10px] font-mono uppercase tracking-widest text-cyan-400 px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20">
                    Live online cohort
                  </span>
                </div>
                <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-4">
                  {flagship.title}
                </h2>
                <p className="text-slate-300 leading-relaxed mb-8">{flagship.description}</p>

                <div className="flex flex-wrap gap-3 mb-8">
                  <MonoBadge icon={<Calendar className="w-3.5 h-3.5" aria-hidden="true" />}>
                    Next: {flagshipDateLabel}
                  </MonoBadge>
                  <MonoBadge icon={<Users className="w-3.5 h-3.5" aria-hidden="true" />}>
                    {flagshipSeatsLabel}
                  </MonoBadge>
                  <MonoBadge icon={<Clock className="w-3.5 h-3.5" aria-hidden="true" />}>
                    {flagshipDurationLabel}
                  </MonoBadge>
                  <MonoBadge icon={<BookOpen className="w-3.5 h-3.5" aria-hidden="true" />}>
                    {flagship.level}
                  </MonoBadge>
                  {flagshipPriceLabel && (
                    <MonoBadge icon={<Tag className="w-3.5 h-3.5" aria-hidden="true" />}>
                      {flagshipPriceLabel} per seat
                    </MonoBadge>
                  )}
                </div>

                <div className="flex flex-col sm:flex-row gap-4">
                  <Link to={`/training/${flagship.slug}`} className="btn-primary">
                    View Course & Register{' '}
                    <ArrowRight className="w-4 h-4" aria-hidden="true" />
                  </Link>
                  <Link to="/contact" className="btn-secondary">
                    Ask a Question
                  </Link>
                </div>
                {flagshipLive?.recordedProductCode && (
                  <Link
                    to={`/training/${flagshipLive.recordedProductCode}`}
                    className="btn-ghost mt-4"
                  >
                    <PlayCircle className="w-4 h-4" aria-hidden="true" />
                    Also available on-demand
                  </Link>
                )}
              </div>

              <div className="lg:col-span-2">
                <Link
                  to={`/training/${flagship.slug}`}
                  className="block rounded-2xl overflow-hidden border border-slate-800 bg-slate-900/50 hover:border-cyan-500/40 transition-colors"
                >
                  <img
                    src="/Mapping_Course_Advertisement.png"
                    alt="Gas Turbine Emissions Mapping — flagship live online course, four live days covering combustion fundamentals, dynamics and DLE operation, emissions and mapping on a simulator, then ambient, flex fuel and troubleshooting."
                    className="w-full h-auto block"
                    width={1671}
                    height={941}
                    loading="lazy"
                  />
                </Link>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      {/* ON-DEMAND — self-paced, buy once, keep forever */}
      <section className="pb-20">
        <div className="container-site">
          <Reveal>
            <div className="card card-hover p-7 md:p-10">
              <div className="grid lg:grid-cols-[1.6fr_1fr] gap-8 items-center">
                <div>
                  <div className="flex flex-wrap items-center gap-3 mb-5">
                    <span className="text-[10px] font-mono uppercase tracking-widest text-cyan-400 px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20">
                      Turbomachinery
                    </span>
                    <span className="text-[10px] font-mono uppercase tracking-widest text-slate-300 px-2.5 py-1 rounded-full bg-slate-800/80 border border-slate-700">
                      Available Now
                    </span>
                  </div>
                  <h3 className="text-2xl md:text-3xl font-bold mb-4 leading-snug">
                    Micro Gas Turbine Design
                  </h3>
                  <p className="text-slate-300 leading-relaxed mb-6">
                    Design a 700 N single-shaft turbojet end to end — architecture, centrifugal
                    compressor, evaporative combustor, axial turbine, compressor maps, CFD and
                    combustor analysis. Seven modules, 28.5 hours, with the design spreadsheets and
                    interactive tools used in the sessions.
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono text-slate-300 mb-7">
                    <span className="flex items-center gap-2">
                      <Layers className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                      7 modules
                    </span>
                    <span className="flex items-center gap-2">
                      <Clock className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                      28.5 hrs
                    </span>
                    <span className="flex items-center gap-2">
                      <PlayCircle className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                      16 h video
                    </span>
                    <span className="flex items-center gap-2">
                      <InfinityIcon className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                      Lifetime
                    </span>
                  </div>
                  <div className="flex flex-col sm:flex-row gap-3">
                    <Link to="/training/micro-gas-turbine-design" className="btn-primary">
                      View Course <ArrowRight className="w-4 h-4" aria-hidden="true" />
                    </Link>
                    <Link to="/contact" className="btn-secondary">
                      Team Licences
                    </Link>
                  </div>
                </div>

                <ul className="space-y-3 text-sm lg:border-l lg:border-slate-800 lg:pl-8">
                  {[
                    'Recorded sessions, streamed on any device',
                    'Slide decks, four design calculators, two interactive tools',
                    'Module quizzes that gate the next module',
                    'Certificate with public verification',
                  ].map((t) => (
                    <li key={t} className="flex gap-2.5 text-slate-300">
                      <Award className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* COMING NEXT — waitlist catalog */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site">
          <SectionHeading
            eyebrow="Coming Next"
            title="Seven Programs in Development"
            subtitle="Built from complete course material and decades of field practice. Join a waitlist and we'll email you when a course opens for enrollment; strong waitlists get scheduled first."
          />
          {TRACKS.map((track) => (
            <div key={track.name} className="mb-14 last:mb-0">
              <Reveal>
                <div className="mb-7 max-w-3xl">
                  <span className="eyebrow">{track.name}</span>
                  <p className="text-slate-400 text-sm leading-relaxed mt-3">{track.intro}</p>
                </div>
              </Reveal>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {track.courses.map((course, i) => (
                  <UpcomingCard key={course.slug} course={course} index={i} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <CTABand
        title="Need Training Built Around Your Fleet?"
        subtitle="We tailor any program to your hardware, your data, and your team's experience level. Delivered on-site or live online."
        primaryLabel="Ask About Custom Training"
        primaryTo="/contact"
      />
    </div>
  );
};

/* ---------- Mono badge for live course facts ---------- */
const MonoBadge = ({
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

export default Training;
