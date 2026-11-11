import React from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Award,
  BookOpen,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  ExternalLink,
  FileText,
  GraduationCap,
  Lightbulb,
} from 'lucide-react';
import { Reveal, SectionHeading, StatCounter } from '../../components/ui';
import Img from '../../components/Img';
import { usePageMeta } from '../../lib/meta';
import { CONSULT_PUBLIC, PROFILE_PUBLIC } from '../../lib/features';
import {
  AWARDS,
  CREDENTIALS,
  EARLIER,
  EARLIER_NAME,
  EDUCATION,
  EXPERIENCE,
  EXPERTISE,
  NAME,
  PATENTS,
  PATENT_SUMMARY,
  PROFILE_LINKS,
  PUBLICATIONS,
  PUBLICATION_SUMMARY,
  RECOGNITION_SUMMARY,
  ROLE,
  STATS,
  SUMMARY,
  type Role,
} from './bassamProfile';

/* /about/bassam-abdelnabi: the expert's profile.
 *
 * Prerendered like the other marketing pages and listed in the sitemap. The
 * facts live in bassamProfile.ts and come from his curricula vitae only.
 *
 * PRICE RULE: no consulting rate appears on this page, its meta or JSON-LD.
 * The call to action links to /consult, where the rate is shown when a
 * visitor picks a time. */

const ORIGIN = 'https://proreadyengineer.com';
const PATH = '/about/bassam-abdelnabi';

const personLd = {
  '@context': 'https://schema.org',
  '@type': 'ProfilePage',
  '@id': `${ORIGIN}${PATH}`,
  url: `${ORIGIN}${PATH}`,
  name: `${NAME}, ${ROLE}`,
  mainEntity: {
    '@type': 'Person',
    '@id': `${ORIGIN}${PATH}#person`,
    name: 'Bassam Abdelnabi',
    honorificPrefix: 'Dr.',
    alternateName: EARLIER_NAME,
    jobTitle: 'Founder and President',
    worksFor: { '@id': `${ORIGIN}/#org` },
    url: `${ORIGIN}${PATH}`,
    image: `${ORIGIN}/Bassam.jpg`,
    description: SUMMARY,
    alumniOf: [
      { '@type': 'CollegeOrUniversity', name: 'University of Cincinnati' },
      { '@type': 'CollegeOrUniversity', name: 'University of Missouri-Rolla (Missouri S&T)' },
      { '@type': 'CollegeOrUniversity', name: 'Cairo University' },
    ],
    hasCredential: EDUCATION.map((d) => ({
      '@type': 'EducationalOccupationalCredential',
      credentialCategory: 'degree',
      name: d.degree,
      recognizedBy: { '@type': 'CollegeOrUniversity', name: d.school },
    })),
    knowsAbout: [
      'Gas turbine combustion',
      'DLE/DLN combustion',
      'Low-NOx systems',
      'Combustion dynamics',
      'Emissions mapping',
      'Fuel flexibility',
      'Hydrogen combustion',
      'Digital twins',
      'Design of Experiments',
      'High-pressure combustion testing',
      'Test-cell commissioning',
    ],
    award: AWARDS.map((a) => `${a.name} (${a.year})`),
    sameAs: [PROFILE_LINKS.linkedin, PROFILE_LINKS.scholar],
  },
};

const RoleCard = ({ role }: { role: Role }) => (
  <li>
    <Reveal className="card p-6 md:p-7">
    <div className="flex flex-col gap-1 md:flex-row md:items-baseline md:justify-between md:gap-6">
      <div className="min-w-0">
        <h3 className="text-lg font-bold leading-snug">{role.title}</h3>
        <p className="text-cyan-300 text-sm font-medium mt-1">
          {role.org}
          {role.place ? <span className="text-slate-400 font-normal">, {role.place}</span> : null}
        </p>
      </div>
      <p className="font-mono text-xs uppercase tracking-wider text-slate-400 md:text-right md:shrink-0">
        {role.dates}
      </p>
    </div>
    <ul className="mt-4 space-y-2.5">
      {role.points.map((p) => (
        <li key={p} className="flex items-start gap-3">
          <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0 mt-1" aria-hidden="true" />
          <span className="text-slate-300 text-sm leading-relaxed">{p}</span>
        </li>
      ))}
    </ul>
    </Reveal>
  </li>
);

const BassamAbdelnabi = () => {
  usePageMeta(
    `${NAME}: Founder and President`,
    'Profile of Dr. Bassam Abdelnabi, founder and president of ProReadyEngineer LLC: a gas turbine combustion engineer with 24 years of experience across research, product programs and field work, a Ph.D. in Aerospace Engineering, nine U.S. patents or patent applications, more than 20 published technical papers and close to 100 internal technical publications.',
    { jsonLd: personLd, image: `${ORIGIN}/Bassam.jpg`, noindex: !PROFILE_PUBLIC },
  );

  return (
    <div>
      {/* ---------- Hero ---------- */}
      <section className="relative pt-36 pb-16 lg:pt-44 lg:pb-20 overflow-hidden">
        <div className="hero-backdrop" />
        <div className="absolute inset-0 -z-10 bg-hero-radial" />
        <div className="container-site max-w-6xl">
          <div className="anim-hero grid grid-cols-1 md:grid-cols-[minmax(0,260px)_1fr] gap-8 md:gap-12 items-center">
            <Img
              src="/Bassam.jpg"
              alt={`Portrait of ${NAME}`}
              sizes="(min-width: 768px) 260px, 220px"
              priority
              className="w-[220px] md:w-full max-w-[260px] mx-auto rounded-2xl border border-slate-800 object-cover shadow-card"
            />
            <div className="text-center md:text-left min-w-0">
              <span className="eyebrow mb-5">About the Expert</span>
              <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight mt-4 mb-3">
                Dr. Bassam <span className="text-gradient">Abdelnabi</span>
              </h1>
              <p className="text-cyan-300 font-medium mb-5">{ROLE}</p>
              <p className="text-lg text-slate-300 leading-relaxed max-w-3xl">{SUMMARY}</p>
              <div className="mt-8 flex flex-col sm:flex-row justify-center md:justify-start gap-4">
                {CONSULT_PUBLIC && (
                  <Link to="/consult" className="btn-primary">
                    <CalendarClock className="w-4 h-4" aria-hidden="true" /> Book a call
                  </Link>
                )}
                <Link to="/insights" className="btn-secondary">
                  Read his research insights
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- At a glance ---------- */}
      <section className="pb-16 lg:pb-20" aria-label="Career at a glance">
        <div className="container-site max-w-6xl">
          <Reveal className="card px-6 py-10 md:px-10">
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-x-6 gap-y-10">
              {STATS.map((s) => (
                <StatCounter key={s.label} value={s.value} suffix={s.suffix ?? ''} label={s.label} />
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------- Experience ---------- */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site max-w-5xl">
          <SectionHeading
            align="left"
            eyebrow="Experience"
            title={<>Industry <span className="text-gradient">experience</span></>}
          />
          <ol className="space-y-6">
            {EXPERIENCE.map((r) => (
              <RoleCard key={r.title + r.dates} role={r} />
            ))}
          </ol>

          <Reveal className="mt-14 mb-6">
            <h2 className="text-xl font-bold flex items-center gap-2">
              <Briefcase className="w-5 h-5 text-cyan-400" aria-hidden="true" /> Earlier research and teaching
            </h2>
          </Reveal>
          <ol className="space-y-6">
            {EARLIER.map((r) => (
              <RoleCard key={r.title + r.dates} role={r} />
            ))}
          </ol>
        </div>
      </section>

      {/* ---------- Expertise ---------- */}
      <section className="section-pad">
        <div className="container-site max-w-6xl">
          <SectionHeading eyebrow="Expertise" title="Technical and digital expertise" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {EXPERTISE.map((e, i) => (
              <Reveal key={e.area} delay={i * 0.08} className="h-full">
                <div className="card h-full p-6">
                  <h3 className="text-base font-bold mb-3 flex items-start gap-2">
                    <Lightbulb className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                    {e.area}
                  </h3>
                  <p className="text-slate-300 text-sm leading-relaxed">{e.items}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- Education ---------- */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site max-w-5xl">
          <SectionHeading align="left" eyebrow="Education" title="Degrees" />
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {EDUCATION.map((d) => (
              <li key={d.degree + d.school}>
                <Reveal className="card h-full p-6">
                  <div className="flex items-start gap-3">
                    <span className="shrink-0 p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20">
                      <GraduationCap className="w-5 h-5 text-cyan-400" aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="text-base font-bold leading-snug">{d.degree}</h3>
                      <p className="text-cyan-300 text-sm mt-1">
                        {d.school}, {d.year}
                      </p>
                      {d.note && <p className="text-slate-300 text-sm leading-relaxed mt-2">{d.note}</p>}
                    </div>
                  </div>
                </Reveal>
              </li>
            ))}
          </ul>
          <Reveal className="mt-8">
            <p className="text-slate-300 text-sm leading-relaxed">
              <span className="font-semibold text-white">Credentials: </span>
              {CREDENTIALS}
            </p>
          </Reveal>
        </div>
      </section>

      {/* ---------- Patents ---------- */}
      <section className="section-pad">
        <div className="container-site max-w-5xl">
          <SectionHeading
            align="left"
            eyebrow="Intellectual Property"
            title="Patents and applications"
            subtitle={PATENT_SUMMARY}
          />
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {PATENTS.map((p) => (
              <li key={p.id}>
                <Reveal className="card h-full p-5 flex items-start gap-3">
                  <FileText className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-white leading-snug">{p.title}</p>
                    <p className="font-mono text-xs text-slate-300 mt-1.5 break-words">
                      {p.id} · {p.year}
                    </p>
                  </div>
                </Reveal>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ---------- Publications ---------- */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site max-w-5xl">
          <SectionHeading
            align="left"
            eyebrow="Research"
            title="Selected publications"
            subtitle={PUBLICATION_SUMMARY}
          />
          <ol className="space-y-4">
            {PUBLICATIONS.map((p) => (
              <li key={p.title}>
                <Reveal className="card p-5 flex items-start gap-3">
                  <BookOpen className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-white leading-snug">{p.title}</p>
                    <p className="text-sm text-slate-300 mt-1.5 break-words">{p.authors}</p>
                    <p className="text-sm text-slate-400 mt-1 break-words">{p.venue}</p>
                  </div>
                </Reveal>
              </li>
            ))}
          </ol>
          <Reveal className="mt-8 flex flex-wrap gap-x-8 gap-y-3">
            <a href={PROFILE_LINKS.scholar} target="_blank" rel="noopener noreferrer" className="btn-ghost">
              Google Scholar profile <ExternalLink className="w-4 h-4" aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
            <a href={PROFILE_LINKS.linkedin} target="_blank" rel="noopener noreferrer" className="btn-ghost">
              LinkedIn profile <ExternalLink className="w-4 h-4" aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
            <Link to="/insights" className="btn-ghost">
              Research insights on this site <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </Link>
          </Reveal>
        </div>
      </section>

      {/* ---------- Recognition ---------- */}
      <section className="section-pad">
        <div className="container-site max-w-5xl">
          <SectionHeading
            align="left"
            eyebrow="Recognition"
            title="Awards"
            subtitle={RECOGNITION_SUMMARY}
          />
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {AWARDS.map((a) => (
              <li key={a.name}>
                <Reveal className="card h-full p-5 flex items-start gap-3">
                  <Award className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="text-sm text-slate-200 leading-snug">{a.name}</p>
                    <p className="font-mono text-xs text-slate-400 mt-1.5">{a.year}</p>
                  </div>
                </Reveal>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ---------- Next step ---------- */}
      <section className="section-pad relative overflow-hidden">
        <div className="absolute inset-0 -z-10 bg-hero-radial" />
        <div className="container-site">
          <Reveal className="card relative overflow-hidden text-center px-6 py-16 md:px-16">
            <div
              className="absolute -top-24 left-1/2 -translate-x-1/2 w-[60%] h-48 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">
              Bring your problem to a <span className="text-gradient">one-to-one call</span>
            </h2>
            <p className="text-slate-300 max-w-2xl mx-auto mb-8">
              Pick a time from the live calendar and meet Dr. Abdelnabi on Google Meet. Courses he created:{' '}
              <Link to="/training/micro-gas-turbine-design" className="text-cyan-400 hover:text-cyan-300">
                Micro Gas Turbine Design
              </Link>{' '}
              and{' '}
              <Link to="/training/gas-turbine-emissions-mapping" className="text-cyan-400 hover:text-cyan-300">
                Gas Turbine Emissions Mapping
              </Link>
              .
            </p>
            <div className="flex flex-col sm:flex-row justify-center gap-4">
              {CONSULT_PUBLIC && (
                <Link to="/consult" className="btn-primary">
                  Book a call <ArrowRight className="w-4 h-4" aria-hidden="true" />
                </Link>
              )}
              <Link to="/contact" className="btn-secondary">
                Ask a question first
              </Link>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
};

export default BassamAbdelnabi;
