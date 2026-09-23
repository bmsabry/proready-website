/**
 * Team, on-site and international training — the sections of /training that
 * sell training delivered where the client wants it: at their facility
 * anywhere in the world, at a regional venue (Istanbul, Dubai, Cairo…), in
 * Cincinnati, or live online, in English or Arabic; plus the fundamentals
 * courses that are taught on request, and the request form.
 *
 * The form posts to the support desk (/api/support/contact) with
 * kind "team_training": the ticket is always filed as a corporate training
 * enquiry and escalated to Bassam, never answered by the AI, so a lead
 * cannot be lost to an automated reply (see support_service).
 */
import React, { useState } from 'react';
import {
  ArrowRight,
  Award,
  Building2,
  CheckCircle2,
  Flame,
  Gauge,
  Languages,
  Landmark,
  MapPin,
  MonitorPlay,
  Send,
  Sparkles,
  Thermometer,
} from 'lucide-react';
import { Reveal } from '../../components/ui';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

export const TEAM_FORM_ID = 'team-training';

/* ---------------- Where we deliver ---------------- */

type Delivery = {
  icon: React.ReactNode;
  title: string;
  tag: string;
  body: string;
  points: string[];
};

const DELIVERY: Delivery[] = [
  {
    icon: <Building2 className="w-6 h-6" aria-hidden="true" />,
    title: 'At Your Facility',
    tag: 'Anywhere in the world',
    body: 'We travel to your plant, training center, or offices and teach your team on site. Examples and exercises are built around the units, fuels, and operating data your engineers work with every day.',
    points: [
      'No travel for your team',
      'Content tailored to your fleet',
      'The most economical option for larger groups',
    ],
  },
  {
    icon: <MapPin className="w-6 h-6" aria-hidden="true" />,
    title: 'At a Regional Venue',
    tag: 'Istanbul · Dubai · Cairo · your choice',
    body: 'Prefer to send your engineers away from daily operations to focus? We run the course at a professional conference venue in a regional hub such as Istanbul, Dubai, or Cairo, or in another city you choose.',
    points: [
      'A short flight from most Gulf capitals',
      'We arrange the venue and training logistics',
      'Trainees from several sites or companies can join together',
    ],
  },
  {
    icon: <Landmark className="w-6 h-6" aria-hidden="true" />,
    title: 'In Cincinnati, USA',
    tag: 'Our home base',
    body: 'Train where we are based. Greater Cincinnati is a center of the US jet-engine industry and home to GE Aerospace’s Evendale campus. Courses run at a professional conference venue in the Cincinnati area.',
    points: [
      'Invitation letters provided for visa applications',
      'Plan early: US visa appointment waits vary by country',
      'Groups from one company or several',
    ],
  },
  {
    icon: <MonitorPlay className="w-6 h-6" aria-hidden="true" />,
    title: 'Live Online',
    tag: 'Your time zone',
    body: 'Join one of our scheduled live cohorts, or book private live sessions for your team, timed around your working hours and time zone.',
    points: [
      'Live with the instructor, not recorded lectures',
      'Private sessions for your team only',
      'Ideal for teams spread across sites',
    ],
  },
];

export const DeliveryOptions = () => (
  <section className="pt-2 pb-16" aria-labelledby="delivery-heading">
    <div className="container-site">
      <Reveal className="text-center mb-14">
        <span className="eyebrow mb-4">In-House &amp; International Training</span>
        <h2 id="delivery-heading" className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">
          Training Where Your Team <span className="text-gradient">Needs It</span>
        </h2>
        <p className="text-slate-300 leading-relaxed max-w-2xl mx-auto">
          We travel to deliver our courses for your team, at your facility or at a venue in the
          city that suits you, or you can bring your engineers to us in Cincinnati. Every course
          can be delivered in English or Arabic.
        </p>
      </Reveal>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
        {DELIVERY.map((d, i) => (
          <Reveal key={d.title} delay={i * 0.07} className="h-full">
            <div className="card card-hover p-7 h-full flex flex-col">
              <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-5">
                {d.icon}
              </div>
              <h3 className="text-lg font-bold mb-1">{d.title}</h3>
              <p className="text-[11px] font-mono uppercase tracking-widest text-cyan-400 mb-4">
                {d.tag}
              </p>
              <p className="text-slate-300 text-sm leading-relaxed mb-5">{d.body}</p>
              <ul className="space-y-2 mt-auto">
                {d.points.map((p) => (
                  <li key={p} className="flex gap-2.5 text-sm text-slate-300 leading-snug">
                    <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          </Reveal>
        ))}
      </div>

      {/* Instructor + language strip */}
      <Reveal delay={0.1}>
        <div className="card mt-8 p-6 md:p-8 grid grid-cols-1 lg:grid-cols-5 gap-6 items-center">
          <div className="lg:col-span-3 flex items-center gap-5">
            <img
              src="/Bassam.jpg"
              alt="Dr. Bassam Abdelnabi"
              className="w-20 h-20 rounded-2xl object-cover border border-slate-700 shrink-0"
              width={80}
              height={80}
              loading="lazy"
              decoding="async"
            />
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-slate-400 mb-1">
                Your instructor
              </p>
              <p className="text-lg font-bold text-white">Dr. Bassam Abdelnabi</p>
              <p className="text-sm text-slate-300 leading-relaxed mt-1">
                Ph.D. in Aerospace Engineering, with over a decade of leadership at GE Aerospace
                and GE Global Research in combustion system design and testing. Gas turbine
                combustion and DLE emissions specialist.
              </p>
            </div>
          </div>
          <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-3">
            <div className="flex items-start gap-3 rounded-xl bg-slate-950/60 border border-slate-700/50 p-4">
              <Languages className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
              <div>
                <p className="text-sm font-semibold text-white">English or Arabic</p>
                <p className="text-sm text-slate-300 mt-0.5" dir="rtl" lang="ar">
                  نقدم التدريب باللغتين العربية والإنجليزية
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-xl bg-slate-950/60 border border-slate-700/50 p-4">
              <Award className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
              <div>
                <p className="text-sm font-semibold text-white">Certificate for every trainee</p>
                <p className="text-sm text-slate-300 mt-0.5">Issued on completion of the course</p>
              </div>
            </div>
          </div>
        </div>
      </Reveal>

      <Reveal delay={0.15} className="flex flex-col sm:flex-row justify-center gap-4 mt-10">
        <a href={`#${TEAM_FORM_ID}`} className="btn-primary">
          Plan Training for Your Team <ArrowRight className="w-4 h-4" aria-hidden="true" />
        </a>
        <a href="#open-courses" className="btn-secondary">
          See Open Courses
        </a>
      </Reveal>
    </div>
  </section>
);

/* ---------------- Beyond the catalog ---------------- */

type OnRequest = {
  icon: React.ReactNode;
  title: string;
  body: string;
  audience: string;
};

const ON_REQUEST: OnRequest[] = [
  {
    icon: <Flame className="w-6 h-6" aria-hidden="true" />,
    title: 'Combustion & Emissions Fundamentals',
    body: 'How flames are stabilized and why they blow out or flash back, how NOx and CO form, how DLE and DLN systems control emissions, and what compliance testing actually measures.',
    audience: 'Operators, technicians, and engineers new to combustion or moving onto DLE units.',
  },
  {
    icon: <Thermometer className="w-6 h-6" aria-hidden="true" />,
    title: 'Thermal-Fluid Fundamentals',
    body: 'Applied thermodynamics, fluid mechanics, and heat transfer, taught through the equipment plant engineers work with: gas turbines, compressors, combustors, and heat exchangers.',
    audience: 'Graduate and early-career engineers, and technicians moving into engineering roles.',
  },
  {
    icon: <Gauge className="w-6 h-6" aria-hidden="true" />,
    title: 'Testing & Instrumentation Fundamentals',
    body: 'Pressure, temperature, and flow measurement; emissions sampling and gas analysis; data acquisition; and how to plan a test and trust its results.',
    audience: 'Test, performance, and commissioning engineers and technicians.',
  },
];

export const BeyondCatalog = () => (
  <section className="section-pad" aria-labelledby="on-request-heading">
    <div className="container-site">
      <Reveal className="text-center mb-14">
        <span className="eyebrow mb-4">On Request</span>
        <h2 id="on-request-heading" className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">
          Courses Beyond the Catalog
        </h2>
        <p className="text-slate-300 leading-relaxed max-w-2xl mx-auto">
          The courses listed on this page are only part of what we teach. We also run
          fundamentals courses that are not scheduled publicly, and we build training to order.
          Every request is discussed and priced for your team.
        </p>
      </Reveal>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
        {ON_REQUEST.map((c, i) => (
          <Reveal key={c.title} delay={i * 0.07} className="h-full">
            <div className="card card-hover p-7 h-full flex flex-col">
              <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-5">
                {c.icon}
              </div>
              <h3 className="text-lg font-bold mb-3 leading-snug">{c.title}</h3>
              <p className="text-slate-300 text-sm leading-relaxed mb-4">{c.body}</p>
              <p className="text-xs text-slate-400 mt-auto">
                <span className="text-slate-300 font-medium">For:</span> {c.audience}
              </p>
            </div>
          </Reveal>
        ))}
        <Reveal delay={0.21} className="h-full">
          <div className="card p-7 h-full flex flex-col border-cyan-500/30 bg-gradient-to-br from-cyan-900/20 via-slate-900/60 to-blue-900/20">
            <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-5">
              <Sparkles className="w-6 h-6" aria-hidden="true" />
            </div>
            <h3 className="text-lg font-bold mb-3 leading-snug">Something Else?</h3>
            <p className="text-slate-300 text-sm leading-relaxed mb-5">
              Tell us the topic, the level, and who needs it. If it is within our expertise, from
              gas turbines and combustion to rotating equipment, test facilities, and industrial
              AI, we will build the course around your team.
            </p>
            <a href={`#${TEAM_FORM_ID}`} className="btn-secondary mt-auto">
              Request a Course <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </a>
          </div>
        </Reveal>
      </div>

      <Reveal delay={0.1}>
        <p className="text-center text-sm text-slate-400 mt-8">
          Every course on this page can also be run privately for your team, with content adapted
          to your equipment.
        </p>
      </Reveal>
    </div>
  </section>
);

/* ---------------- Request form ---------------- */

const inputClass =
  'w-full bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-100 placeholder:text-slate-400 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/30 transition-colors';
const labelClass = 'block text-xs font-mono font-medium text-slate-300 uppercase tracking-widest mb-2';
const RequiredMark = () => (
  <span className="text-cyan-400 ml-1" aria-hidden="true">
    *
  </span>
);

export const TOPICS = [
  'Gas Turbine Emissions Mapping (DLE tuning)',
  'Micro Gas Turbine Design',
  'Combustion & emissions fundamentals',
  'Thermal-fluid fundamentals',
  'Testing & instrumentation fundamentals',
  'Rotating equipment (pumps, compressors, seals, valves)',
  'Combustor design, combustion testing, or digital twins',
  'Something else (describe below)',
];

export const FORMATS = [
  'At our facility',
  'Regional venue (Istanbul, Dubai, Cairo…)',
  'Cincinnati, USA',
  'Live online',
  'Not sure yet',
];

const GROUP_SIZES = ['1–5', '6–10', '11–20', '21 or more'];
const LANGUAGES = ['English', 'Arabic', 'Either'];

const STEPS = [
  {
    title: 'Tell us about your team',
    body: 'Roles, experience, equipment, and what they must be able to do after the course.',
  },
  {
    title: 'We propose',
    body: 'An outline, duration, format, location, and a quote. Everything is open to discussion.',
  },
  {
    title: 'We tailor',
    body: 'Examples and exercises built around your machines, your fuels, and your data.',
  },
  {
    title: 'We deliver',
    body: 'On site, at a venue, in Cincinnati, or online, in English or Arabic.',
  },
];

/** The request body a human reads in the support inbox and the alert email. */
export function composeRequest(f: {
  company: string;
  country: string;
  phone: string;
  size: string;
  topic: string;
  formats: string[];
  city: string;
  timing: string;
  language: string;
  details: string;
}): { subject: string; message: string } {
  const fields = [
    ['Company', f.company],
    ['Country', f.country],
    ['Phone / WhatsApp', f.phone],
    ['Trainees', f.size],
    ['Course or topic', f.topic],
    ['Where', f.formats.join('; ')],
    ['Preferred city', f.city],
    ['Timing', f.timing],
    ['Language', f.language],
  ]
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}: ${v}`);
  const message = [
    'Team training request (Training page form)',
    '',
    ...fields,
    '',
    'About the team and goals:',
    f.details,
  ].join('\n');
  const where = f.country ? ` (${f.country})` : '';
  return { subject: `Team training request: ${f.company}${where}`.slice(0, 300), message };
}

export const TeamTrainingForm = () => {
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [ref, setRef] = useState<string | null>(null);
  const [formats, setFormats] = useState<string[]>([]);
  const [language, setLanguage] = useState('Either');

  const toggleFormat = (f: string) =>
    setFormats((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!API_BASE) {
      setState('error');
      setError('The form is temporarily unavailable. Please email info@proreadyengineer.com.');
      return;
    }
    const form = new FormData(e.currentTarget);
    const get = (k: string) => String(form.get(k) ?? '').trim();
    const { subject, message } = composeRequest({
      company: get('company'),
      country: get('country'),
      phone: get('phone'),
      size: get('size'),
      topic: get('topic'),
      formats,
      city: get('city'),
      timing: get('timing'),
      language,
      details: get('details'),
    });
    setState('busy');
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/support/contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: get('name'),
          email: get('email'),
          subject,
          message,
          kind: 'team_training',
          website: get('website'),
        }),
      });
      const data = (await res.json().catch(() => ({}))) as { ref?: string; detail?: unknown };
      if (res.ok) {
        setRef(data.ref ?? null);
        setState('done');
      } else {
        setState('error');
        setError(
          typeof data.detail === 'string'
            ? data.detail
            : 'Please check the email address and try again, or email info@proreadyengineer.com.',
        );
      }
    } catch {
      setState('error');
      setError('Could not send your request. Please check your connection, or email info@proreadyengineer.com.');
    }
  };

  return (
    <section id={TEAM_FORM_ID} className="section-pad scroll-mt-24 bg-slate-900/30" aria-labelledby="team-form-heading">
      <div className="container-site">
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-10 lg:gap-14 items-start">
          {/* LEFT — how it works */}
          <Reveal className="lg:col-span-2">
            <span className="eyebrow mb-4">Team &amp; Custom Training</span>
            <h2 id="team-form-heading" className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">
              Plan Training for <span className="text-gradient">Your Team</span>
            </h2>
            <p className="text-slate-300 leading-relaxed mb-8">
              Tell us who needs training, what they need to learn, and where you want it
              delivered. We reply within one business day with next steps, then send a proposed
              outline, format, dates, and a quote.
            </p>
            <ol className="space-y-5 mb-8">
              {STEPS.map((s, i) => (
                <li key={s.title} className="flex gap-4">
                  <span className="w-9 h-9 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 font-mono text-sm flex items-center justify-center shrink-0">
                    {i + 1}
                  </span>
                  <div>
                    <p className="font-semibold text-white">{s.title}</p>
                    <p className="text-sm text-slate-300 leading-relaxed">{s.body}</p>
                  </div>
                </li>
              ))}
            </ol>
            <div className="rounded-xl bg-slate-950/60 border border-slate-700/50 p-5" dir="rtl" lang="ar">
              <p className="text-sm font-semibold text-white mb-2">للشركات في الشرق الأوسط وشمال أفريقيا</p>
              <p className="text-sm text-slate-300 leading-loose">
                نقدم دوراتنا في موقع شركتكم في أي مكان في العالم، أو في قاعات تدريب احترافية في مدن
                مثل إسطنبول ودبي والقاهرة، أو في مدينة سينسيناتي بالولايات المتحدة الأمريكية.
                يُقدَّم التدريب باللغتين العربية والإنجليزية، ويمكن تصميم أي دورة وفق احتياجات
                فريقكم. تواصلوا معنا عبر هذا النموذج، ويسعدنا الرد عليكم باللغة العربية.
              </p>
            </div>
            <p className="text-sm text-slate-400 mt-6">
              Prefer email?{' '}
              <a href="mailto:info@proreadyengineer.com" className="text-cyan-400 hover:text-cyan-300">
                info@proreadyengineer.com
              </a>
            </p>
          </Reveal>

          {/* RIGHT — form */}
          <Reveal delay={0.1} className="lg:col-span-3">
            <div className="card relative overflow-hidden p-8 md:p-10">
              <div
                className="absolute -top-20 right-0 w-72 h-48 bg-cyan-500/10 blur-[90px] rounded-full pointer-events-none"
                aria-hidden="true"
              />
              {state === 'done' ? (
                <div className="text-center py-12" role="status">
                  <div className="w-20 h-20 bg-cyan-500/15 border border-cyan-500/30 rounded-full flex items-center justify-center mx-auto mb-6">
                    <CheckCircle2 className="w-10 h-10 text-cyan-400" aria-hidden="true" />
                  </div>
                  <h3 className="text-2xl font-bold mb-4">Request Received</h3>
                  <p className="text-slate-300 mb-4 max-w-md mx-auto">
                    Thank you. Your request has reached Dr. Abdelnabi. You&rsquo;ll get a
                    confirmation by email shortly, and a personal reply within one business day.
                  </p>
                  {ref && ref !== '00000000' && (
                    <p className="text-sm text-slate-400">
                      Your reference: <span className="font-mono text-cyan-400">#{ref}</span>
                    </p>
                  )}
                </div>
              ) : (
                <form onSubmit={submit} className="relative space-y-6">
                  {state === 'error' && error && (
                    <div role="alert" className="text-sm border rounded-lg px-4 py-3 text-red-200 bg-red-950/40 border-red-900/60">
                      {error}
                    </div>
                  )}
                  <div className="absolute left-[-9999px] w-px h-px overflow-hidden" aria-hidden="true">
                    <label htmlFor="tt-website">Leave this field empty</label>
                    <input id="tt-website" type="text" name="website" tabIndex={-1} autoComplete="off" />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label htmlFor="tt-name" className={labelClass}>
                        Full Name
                        <RequiredMark />
                      </label>
                      <input required id="tt-name" name="name" type="text" autoComplete="name" className={inputClass} />
                    </div>
                    <div>
                      <label htmlFor="tt-email" className={labelClass}>
                        Work Email
                        <RequiredMark />
                      </label>
                      <input required id="tt-email" name="email" type="email" autoComplete="email" className={inputClass} placeholder="you@company.com" />
                    </div>
                    <div>
                      <label htmlFor="tt-company" className={labelClass}>
                        Company
                        <RequiredMark />
                      </label>
                      <input required id="tt-company" name="company" type="text" autoComplete="organization" className={inputClass} />
                    </div>
                    <div>
                      <label htmlFor="tt-country" className={labelClass}>
                        Country
                        <RequiredMark />
                      </label>
                      <input required id="tt-country" name="country" type="text" autoComplete="country-name" className={inputClass} />
                    </div>
                    <div>
                      <label htmlFor="tt-phone" className={labelClass}>
                        Phone or WhatsApp
                      </label>
                      <input id="tt-phone" name="phone" type="tel" autoComplete="tel" className={inputClass} placeholder="Optional" />
                    </div>
                    <div>
                      <label htmlFor="tt-size" className={labelClass}>
                        Number of Trainees
                      </label>
                      <select id="tt-size" name="size" className={`${inputClass} appearance-none`} defaultValue="">
                        <option value="">Select…</option>
                        {GROUP_SIZES.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div>
                    <label htmlFor="tt-topic" className={labelClass}>
                      Course or Topic
                    </label>
                    <select id="tt-topic" name="topic" className={`${inputClass} appearance-none`} defaultValue="">
                      <option value="">Select…</option>
                      {TOPICS.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>

                  <fieldset>
                    <legend className={labelClass}>Where Would You Like the Training?</legend>
                    <div className="flex flex-wrap gap-2">
                      {FORMATS.map((f) => {
                        const on = formats.includes(f);
                        return (
                          <button
                            key={f}
                            type="button"
                            aria-pressed={on}
                            onClick={() => toggleFormat(f)}
                            className={`px-3.5 py-2 rounded-lg text-sm border transition-colors ${
                              on
                                ? 'bg-cyan-500/15 border-cyan-400 text-cyan-200'
                                : 'bg-slate-900/60 border-slate-700 text-slate-300 hover:border-slate-500'
                            }`}
                          >
                            {f}
                          </button>
                        );
                      })}
                    </div>
                  </fieldset>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label htmlFor="tt-city" className={labelClass}>
                        Preferred City
                      </label>
                      <input id="tt-city" name="city" type="text" className={inputClass} placeholder="Optional" />
                    </div>
                    <div>
                      <label htmlFor="tt-timing" className={labelClass}>
                        Target Dates
                      </label>
                      <input id="tt-timing" name="timing" type="text" className={inputClass} placeholder="e.g. March 2027" />
                    </div>
                  </div>

                  <fieldset>
                    <legend className={labelClass}>Language</legend>
                    <div className="flex flex-wrap gap-2">
                      {LANGUAGES.map((l) => (
                        <button
                          key={l}
                          type="button"
                          aria-pressed={language === l}
                          onClick={() => setLanguage(l)}
                          className={`px-3.5 py-2 rounded-lg text-sm border transition-colors ${
                            language === l
                              ? 'bg-cyan-500/15 border-cyan-400 text-cyan-200'
                              : 'bg-slate-900/60 border-slate-700 text-slate-300 hover:border-slate-500'
                          }`}
                        >
                          {l}
                        </button>
                      ))}
                    </div>
                  </fieldset>

                  <div>
                    <label htmlFor="tt-details" className={labelClass}>
                      About the Team and Goals
                      <RequiredMark />
                    </label>
                    <textarea
                      required
                      id="tt-details"
                      name="details"
                      rows={5}
                      className={inputClass}
                      placeholder="e.g. 12 O&M engineers at a combined-cycle plant with GE 9F units. We need DLE tuning and emissions troubleshooting before next summer."
                    />
                  </div>

                  <button type="submit" disabled={state === 'busy'} className="btn-primary w-full disabled:opacity-60">
                    {state === 'busy' ? 'Sending…' : 'Send Request'}
                    <Send className="w-4 h-4" aria-hidden="true" />
                  </button>
                  <p className="text-xs text-slate-400 text-center">
                    Your details are used only to reply to this request.
                  </p>
                </form>
              )}
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
};

