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
} from 'lucide-react';
import { Reveal, SectionHeading, CTABand, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';

// Courses backed by the registration API expose a `code` so the card can show
// live seats / start date instead of hardcoded values.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

// Parse "2026-05-16" -> "May 16, 2026" without timezone drift.
const formatStartDate = (iso: string): string => {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  if (!y || !m || !d) return iso;
  const months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];
  return `${months[m - 1]} ${d}, ${y}`;
};

const courses = [
  {
    id: 1,
    title: "Gas Turbine Emissions Mapping",
    category: "Thermal Fluids",
    duration: "5 Days",
    level: "Beginner to Expert",
    attendees: "15 Seats",
    description: "De-mystify DLE combustion. Master the dynamics corridor, emissions mapping strategy, and flex-fuel troubleshooting from first principles to expert level. No prior gas turbine knowledge required.",
    nextDate: "May 15, 2026",
    slug: "gas-turbine-emissions-mapping",
    code: "gas-turbine-emissions-mapping-2026-05",
    featured: true
  },
  {
    id: 2,
    title: "Advanced Combustion Fundamentals",
    category: "Thermal Fluids",
    duration: "3 Days",
    level: "Intermediate",
    attendees: "20 Max",
    description: "Core combustion theory with practical applications for modern energy systems.",
    nextDate: "By request"
  },
  {
    id: 3,
    title: "Fundamentals of Turbomachinery",
    category: "Thermal Fluids",
    duration: "2 Days",
    level: "Foundational",
    attendees: "25 Max",
    description: "Fundamental principles of compressors, turbines, and overall cycle performance.",
    nextDate: "By request"
  },
  {
    id: 4,
    title: "Data Visualization & Advanced Analytics",
    category: "AI & Data",
    duration: "2 Days",
    level: "Intermediate",
    attendees: "20 Max",
    description: "Turn complex data into clear, decision-ready engineering insights.",
    nextDate: "By request"
  },
  {
    id: 5,
    title: "Applied Machine Learning & AI for Engineers",
    category: "AI & Data",
    duration: "4 Days",
    level: "Intermediate",
    attendees: "20 Max",
    description: "Practical ML workflows tailored to engineering datasets and constraints.",
    nextDate: "By request"
  },
  {
    id: 6,
    title: "CFD Best Practices & Simulation",
    category: "Thermal Fluids",
    duration: "2 Days",
    level: "Intermediate",
    attendees: "15 Max",
    description: "Mesh generation, turbulence modeling, and solver strategy for robust CFD.",
    nextDate: "By request"
  },
  {
    id: 7,
    title: "Custom Corporate Training Programs",
    category: "Thermal Fluids",
    duration: "Custom",
    level: "All Levels",
    attendees: "Team-based",
    description: "Tailored programs aligned to your systems, data, and business goals.",
    nextDate: "Schedule with us"
  }
];

type LiveCourseInfo = {
  seatsRemaining: number;
  totalSeats: number;
  startDate: string; // already formatted "May 16, 2026"
  status: 'open' | 'closed';
  numDays: number; // length of day_dates; 0 if not scheduled
};

const WHY_TRAIN = [
  {
    icon: <Award className="w-6 h-6" aria-hidden="true" />,
    title: 'Practitioners, Not Lecturers',
    body: 'Taught by the engineers who design, test, and troubleshoot these systems — ex-GE, PhD-led, with patents in the field.',
  },
  {
    icon: <FlaskConical className="w-6 h-6" aria-hidden="true" />,
    title: 'Real Test-Cell Data & Field Experience',
    body: 'Lessons built on thousands of live mapping tests and real field events — not idealized textbook cases.',
  },
  {
    icon: <MessagesSquare className="w-6 h-6" aria-hidden="true" />,
    title: 'Small Cohorts, Direct Q&A',
    body: 'Limited seats keep every session interactive. Bring your hardest questions straight to the instructor.',
  },
];

const Training = () => {
  usePageMeta(
    'Professional Training',
    'Specialized gas turbine, combustion, and industrial AI training taught by the engineers who design and test these systems. Live cohorts with real test-cell data and direct Q&A.',
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
  const upcoming = courses.filter((c) => !c.featured);

  const flagshipLive = flagship.code ? liveByCode[flagship.code] : undefined;
  const flagshipSeatsLabel = flagshipLive
    ? flagshipLive.status === 'closed'
      ? 'Registration closed'
      : flagshipLive.seatsRemaining === 0
        ? `Cohort full (${flagshipLive.totalSeats} seats)`
        : `${flagshipLive.seatsRemaining} of ${flagshipLive.totalSeats} seats left`
    : flagship.attendees;
  const flagshipDateLabel = flagshipLive ? flagshipLive.startDate : flagship.nextDate;
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
        subtitle="Specialized courses taught by the engineers who design and test gas turbines, combustion systems, and industrial AI — ex-GE, PhD-led, field-proven."
      />

      {/* FLAGSHIP COURSE */}
      <section className="container-site pb-8">
        <Reveal>
          <div className="relative card overflow-hidden p-8 md:p-12">
            <div
              className="absolute -top-32 -right-24 w-96 h-96 bg-cyan-500/10 blur-[120px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-10 items-center relative">
              <div className="lg:col-span-3">
                <span className="eyebrow mb-5">Flagship Course · Live Cohort</span>
                <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4 mb-4">
                  {flagship.title}
                </h2>
                <p className="text-slate-400 leading-relaxed mb-8">{flagship.description}</p>

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
              </div>

              <div className="lg:col-span-2">
                <Link
                  to={`/training/${flagship.slug}`}
                  className="block rounded-2xl overflow-hidden border border-slate-800 bg-slate-900/50 hover:border-cyan-500/40 transition-colors"
                >
                  <img
                    src="/Gas_Turbine_Emissions_Mapping_Infographic.png"
                    alt="Gas Turbine Emissions Mapping course infographic — DLE combustion circuits, dynamics corridor, and mapping workflow"
                    className="w-full h-auto block"
                    loading="lazy"
                  />
                </Link>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      {/* WHY TRAIN WITH US */}
      <section className="section-pad">
        <div className="container-site">
          <SectionHeading
            eyebrow="Why Train With Us"
            title="Field-Grade Knowledge, Transferred Directly"
            subtitle="Every course is built around the decisions you actually face in the test cell and the field — not slides recycled from a textbook."
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {WHY_TRAIN.map((item, i) => (
              <Reveal key={item.title} delay={i * 0.08}>
                <div className="card card-hover p-8 h-full">
                  <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-5">
                    {item.icon}
                  </div>
                  <h3 className="text-lg font-bold mb-3">{item.title}</h3>
                  <p className="text-slate-400 text-sm leading-relaxed">{item.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* UPCOMING / COMING SOON */}
      <section className="pb-20">
        <div className="container-site">
          <SectionHeading
            eyebrow="More Programs"
            title="Coming Soon & By Request"
            subtitle="These programs run as scheduled public cohorts or tailored corporate deliveries. Contact us to schedule one for your team."
          />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {upcoming.map((course, i) => (
              <Reveal key={course.id} delay={(i % 3) * 0.07}>
                <div className="card card-hover p-7 h-full flex flex-col">
                  <div className="flex items-center justify-between gap-3 mb-5">
                    <span className="text-[10px] font-mono uppercase tracking-widest text-cyan-400 px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20">
                      {course.category}
                    </span>
                    <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400 px-2.5 py-1 rounded-full bg-slate-800/80 border border-slate-700">
                      Coming Soon
                    </span>
                  </div>
                  <h3 className="text-lg font-bold mb-3 leading-snug">{course.title}</h3>
                  <p className="text-slate-400 text-sm leading-relaxed mb-6 flex-grow">
                    {course.description}
                  </p>
                  <div className="grid grid-cols-2 gap-3 text-xs font-mono text-slate-400 mb-6">
                    <span className="flex items-center gap-2">
                      <Clock className="w-3.5 h-3.5 text-slate-600" aria-hidden="true" />
                      {course.duration}
                    </span>
                    <span className="flex items-center gap-2">
                      <BookOpen className="w-3.5 h-3.5 text-slate-600" aria-hidden="true" />
                      {course.level}
                    </span>
                    <span className="flex items-center gap-2">
                      <Users className="w-3.5 h-3.5 text-slate-600" aria-hidden="true" />
                      {course.attendees}
                    </span>
                    <span className="flex items-center gap-2">
                      <Calendar className="w-3.5 h-3.5 text-slate-600" aria-hidden="true" />
                      {course.nextDate}
                    </span>
                  </div>
                  <Link to="/contact" className="btn-ghost mt-auto">
                    Request This Course <ArrowRight className="w-4 h-4" aria-hidden="true" />
                  </Link>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <CTABand
        title="Need Training Built Around Your Fleet?"
        subtitle="We tailor any program to your hardware, your data, and your team's experience level — delivered on-site or live online."
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
