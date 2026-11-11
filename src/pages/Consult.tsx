import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  CreditCard,
  FileText,
  ShieldAlert,
  Video,
} from 'lucide-react';
import { PageHero, Reveal, SectionHeading } from '../components/ui';
import Img from '../components/Img';
import BookingFlow, { type AvailabilityState } from '../components/consult/BookingFlow';
import { usePageMeta } from '../lib/meta';
import { CONSULT_PUBLIC, PROFILE_PUBLIC } from '../lib/features';
import {
  consult,
  ConsultError,
  fmtShortDateTime,
  isTimeZone,
  visitorTimeZone,
} from '../lib/consultApi';

/* /consult: book a paid one-to-one video call with the expert.
 *
 * Prerendered like the other marketing pages. Everything that depends on the
 * clock or the calendar (the "Next available" line, the open times) is
 * fetched after hydration, so the static HTML never goes stale and never
 * disagrees with the visitor's browser.
 *
 * PRICE RULE: no amount appears anywhere on this page, its meta or JSON-LD.
 * Amounts are shown only inside the booking flow, from the server's quote. */

const steps = [
  {
    icon: <CalendarClock className="w-6 h-6 text-cyan-400" aria-hidden="true" />,
    title: 'Pick a time',
    desc: 'Choose an open time from the live calendar, shown in your own time zone, and how long you need: 30 minutes to 2 hours. You see the rate and the total before you enter anything.',
  },
  {
    icon: <CreditCard className="w-6 h-6 text-cyan-400" aria-hidden="true" />,
    title: 'Save a card, pay nothing now',
    desc: 'Your card is saved on Stripe’s secure page. Nothing is charged when you book; the call is charged only after the meeting.',
  },
  {
    icon: <Video className="w-6 h-6 text-cyan-400" aria-hidden="true" />,
    title: 'Meet on Google Meet',
    desc: 'As soon as your card is saved you receive a calendar invitation with the Google Meet link, then a reminder two days before, while cancelling is still free, and one an hour before the call.',
  },
];

const topics = [
  'DLN/DLE combustion tuning and troubleshooting',
  'Combustion dynamics: diagnosis and mitigation',
  'Lean blowout margin and operability',
  'Hydrogen and flex-fuel conversion, including H2 blends and liquid fuels',
  'Emissions mapping campaigns and NOx/CO compliance',
  'CFD and conjugate heat transfer review of combustor hardware',
  'Combustor test rig and high-pressure test cell design',
  'Gaseous and liquid fuel systems for test facilities',
  'Emissions sampling systems and probe design',
  'Digital-twin models for emissions optimization',
];

const bring = [
  'A short description of the problem: what the unit or system is doing, since when, and what has already been tried.',
  'The machine and combustion system involved, and the operating range that matters.',
  'Data you are free to share: trends, emissions against load, dynamics spectra, temperature spreads.',
  'Your constraints: permit limits, outage windows, budget, deadlines.',
  'The decision you need to make, so the time goes to what moves it.',
];

const plainTerms = [
  {
    title: 'The rate depends on how soon the call is',
    desc: 'Same day, next day, within the week, or a week or more ahead. The exact rate and total for the time you pick are shown before you confirm, and billing is in 30-minute steps.',
  },
  {
    title: 'Your card is charged only after the meeting',
    desc: 'Saving a card when you book charges nothing. The charge is made once the call has taken place.',
  },
  {
    title: 'A temporary hold before the meeting',
    desc: 'About 24 hours before the call (or right after you save your card, if the call is sooner) a temporary hold for the call’s total is placed on your card. It is not a charge, and it is released or converted to the final charge after the call.',
  },
  {
    title: 'No-show and late cancellation cost 20%',
    desc: 'Cancel free until 24 hours before the start. After that, or if you do not join the call, 20% of the booked amount is charged. A call booked less than 24 hours ahead can still be cancelled free within 15 minutes of booking. If the expert does not join, you are not charged.',
  },
  {
    title: 'What cannot be discussed',
    desc: 'Please do not share third-party proprietary information or export-controlled information (for example, technical data controlled under ITAR or the EAR). It will not be discussed on the call.',
  },
  {
    title: 'Questions about a charge',
    desc: 'Reply to the receipt email. Our support desk handles it and answers by email.',
  },
];

const faqs = [
  {
    q: 'How much does a call cost?',
    a: 'It depends on how soon the call is: same day, next day, within the week, or a week or more ahead. When you pick a time and a length, the booking form shows the hourly rate, the total and the 20% fee amount before you enter any details. Billing is in 30-minute steps.',
  },
  {
    q: 'When is my card charged?',
    a: 'Only after the meeting. Booking saves your card and charges nothing. About 24 hours before the call a temporary hold for the total is placed on the card; it becomes the charge after the call, or is released.',
  },
  {
    q: 'Can I cancel or move my call?',
    a: 'You can cancel free until 24 hours before the start from the link in your confirmation email, then book a new time. Cancelling later costs 20% of the booked amount. A call booked less than 24 hours ahead can be cancelled free within 15 minutes of booking.',
  },
  {
    q: 'What happens if I cannot join?',
    a: 'If you do not join the call, it counts as a no-show and 20% of the booked amount is charged. If the expert does not join, you are not charged at all.',
  },
  {
    q: 'How soon can I talk to someone?',
    a: 'As soon as today, when a same-day time is open. The live calendar on this page shows every open time, starting with the next one available.',
  },
  {
    q: 'What if my problem needs more than one call?',
    a: 'Say so on the call. A larger piece of work, such as a test campaign, a design review or a field visit, is scoped separately as a consulting engagement.',
  },
  {
    q: 'Is there anything you will not discuss?',
    a: 'Third-party proprietary information and export-controlled information are not discussed. Please do not bring them to the call.',
  },
];

const faqLd = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: faqs.map((f) => ({
    '@type': 'Question',
    name: f.q,
    acceptedAnswer: { '@type': 'Answer', text: f.a },
  })),
};

const serviceLd = {
  '@context': 'https://schema.org',
  '@type': 'Service',
  name: 'Consult a Gas Turbine Combustion Expert',
  serviceType: 'Expert consultation by video call',
  provider: { '@id': 'https://proreadyengineer.com/#org' },
  areaServed: 'Worldwide',
  availableChannel: {
    '@type': 'ServiceChannel',
    serviceUrl: 'https://proreadyengineer.com/consult',
    name: 'Google Meet video call',
  },
  description:
    'A one-to-one video call with a gas turbine combustion expert on Google Meet, bookable online from 30 minutes to 2 hours, available as soon as the same day.',
};

const credentials = [
  'Ph.D. in Aerospace Engineering',
  'Led combustion R&D, combustion system design and automated testing at GE Aerospace and GE Global Research',
  'Designs, specifies and builds high-pressure industrial test cells with their air, fuel, quench, measurement and control systems',
  'Digital-twin modelling and field mapping for gas turbine emissions optimization',
  'Hands-on with hydrogen, gaseous fuels and liquid fuels including crude oil',
  'Teaches the Gas Turbine Emissions Mapping course',
];

const Consult = () => {
  usePageMeta(
    'Consult a Gas Turbine Combustion Expert',
    'Book a one-to-one video call with a gas turbine combustion expert, as soon as today. Pick a time from the live calendar, save a card (nothing is charged at booking) and meet on Google Meet.',
    // Hidden release: not indexed, and no structured data advertising it.
    CONSULT_PUBLIC ? { jsonLd: [serviceLd, faqLd] } : { noindex: true },
  );

  // The visitor's zone is only known in the browser; '' until mounted keeps
  // the prerendered HTML identical to the first client render.
  const [tz, setTz] = useState('');
  const [state, setState] = useState<AvailabilityState>({ kind: 'loading' });

  useEffect(() => {
    setTz(visitorTimeZone());
  }, []);

  const load = useCallback(async (zone: string) => {
    try {
      const data = await consult.availability(zone);
      if (!data.enabled) {
        setState({ kind: 'unavailable', reason: '' });
      } else {
        setState({ kind: 'ready', data });
      }
    } catch (e) {
      setState({
        kind: 'unavailable',
        reason:
          e instanceof ConsultError && e.status === 0 && /not configured/i.test(e.message)
            ? ''
            : 'We could not load the calendar just now.',
      });
    }
  }, []);

  useEffect(() => {
    if (!tz) return;
    setState({ kind: 'loading' });
    void load(tz);
  }, [tz, load]);

  const changeTz = (z: string) => {
    if (isTimeZone(z)) setTz(z);
  };

  const next = state.kind === 'ready' ? state.data.next_available : null;
  const nextLine =
    state.kind === 'loading' || !tz ? (
      <span className="text-slate-400">Checking the calendar…</span>
    ) : state.kind === 'unavailable' ? (
      <span className="text-slate-300">Online booking is paused for the moment.</span>
    ) : next ? (
      <>
        <span className="text-slate-300">Next available:</span>{' '}
        <span className="text-white font-semibold">{fmtShortDateTime(next.start, tz)}</span>
      </>
    ) : (
      <span className="text-slate-300">No open times right now.</span>
    );

  return (
    <div>
      <PageHero
        eyebrow="Consult an Expert"
        title={
          <>
            Talk to a gas turbine combustion expert, <span className="text-gradient">as soon as today</span>
          </>
        }
        subtitle="A one-to-one video call with Dr. Bassam Abdelnabi on Google Meet: bring the combustor problem, the data and the decision you are facing, and get a direct, expert answer."
      >
        <div className="mt-8 flex flex-col items-center gap-6">
          <p
            className="inline-flex flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-4 py-2 text-sm"
            aria-live="polite"
            data-testid="consult-next-available"
          >
            <span className="relative flex h-2 w-2" aria-hidden="true">
              <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 animate-ping motion-reduce:animate-none" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            {nextLine}
          </p>
          <div className="flex flex-col sm:flex-row justify-center gap-4">
            <a href="#book" className="btn-primary">
              Pick a time <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </a>
            <Link to="/contact" className="btn-secondary">
              Ask a question first
            </Link>
          </div>
        </div>
      </PageHero>

      {/* ---------- How it works ---------- */}
      <section className="pb-16 lg:pb-20">
        <div className="container-site">
          <SectionHeading eyebrow="How It Works" title="Three steps to a call" />
          <ol className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {steps.map((s, i) => (
              <Reveal key={s.title} delay={i * 0.08} className="h-full">
                <li className="card h-full p-7">
                  <div className="flex items-center gap-3 mb-4">
                    <span className="p-2.5 bg-slate-950 rounded-xl">{s.icon}</span>
                    <span className="font-mono text-xs uppercase tracking-widest text-cyan-400">Step {i + 1}</span>
                  </div>
                  <h3 className="text-lg font-bold mb-2">{s.title}</h3>
                  <p className="text-slate-300 text-sm leading-relaxed">{s.desc}</p>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      {/* ---------- Booking ---------- */}
      <section id="book" className="section-pad bg-slate-900/30 scroll-mt-20">
        <div className="container-site max-w-5xl">
          <SectionHeading
            eyebrow="Book a Call"
            title={<>Choose your <span className="text-gradient">time</span></>}
            subtitle="Open times come straight from the expert's calendar. Nothing is charged when you book."
          />
          <div className="card p-5 sm:p-8">
            <BookingFlow state={state} tz={tz} onTzChange={changeTz} reload={() => load(tz)} />
          </div>
        </div>
      </section>

      {/* ---------- Who you will talk to ---------- */}
      <section className="section-pad">
        <div className="container-site max-w-6xl">
          <div className="grid grid-cols-1 md:grid-cols-[minmax(0,280px)_1fr] gap-10 items-start">
            <Reveal>
              <Img
                src="/Bassam.jpg"
                alt="Dr. Bassam Abdelnabi"
                sizes="(min-width: 768px) 280px, 100vw"
                className="w-full max-w-[280px] mx-auto rounded-2xl border border-slate-800 object-cover"
              />
            </Reveal>
            <Reveal>
              <span className="eyebrow mb-4">Who You Will Talk To</span>
              <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-2">Dr. Bassam Abdelnabi</h2>
              <p className="text-cyan-300 font-medium mb-6">Principal Consultant, Gas Turbine Combustion Expert</p>
              <ul className="space-y-3 mb-8">
                {credentials.map((c) => (
                  <li key={c} className="flex items-start gap-3">
                    <CheckCircle2 className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-slate-300 text-sm leading-relaxed">{c}</span>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-x-6 gap-y-3">
                {PROFILE_PUBLIC && (
                  <Link to="/about/bassam-abdelnabi" className="btn-ghost">
                    Full profile <ArrowRight className="w-4 h-4" aria-hidden="true" />
                  </Link>
                )}
                <Link to="/insights" className="btn-ghost">
                  Read his research insights <ArrowRight className="w-4 h-4" aria-hidden="true" />
                </Link>
                <Link to="/case-studies" className="btn-ghost">
                  Case studies <ArrowRight className="w-4 h-4" aria-hidden="true" />
                </Link>
                <Link to="/testimonials" className="btn-ghost">
                  What engineers say <ArrowRight className="w-4 h-4" aria-hidden="true" />
                </Link>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- What to bring ---------- */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site">
          <SectionHeading
            eyebrow="Make It Count"
            title="What to bring to a call"
            subtitle="A call is most useful when it starts from the facts. Bring what you can share; the rest can follow."
          />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <Reveal className="card p-7 h-full">
              <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                <FileText className="w-5 h-5 text-cyan-400" aria-hidden="true" /> Bring
              </h3>
              <ul className="space-y-3">
                {bring.map((b) => (
                  <li key={b} className="flex items-start gap-3">
                    <CheckCircle2 className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-slate-300 text-sm leading-relaxed">{b}</span>
                  </li>
                ))}
              </ul>
            </Reveal>
            <Reveal className="card p-7 h-full">
              <h3 className="text-lg font-bold mb-4">Example topics</h3>
              <ul className="flex flex-wrap gap-2">
                {topics.map((t) => (
                  <li
                    key={t}
                    className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1.5 text-sm text-slate-200"
                  >
                    {t}
                  </li>
                ))}
              </ul>
              <p className="mt-5 text-sm text-slate-400">
                More on each area:{' '}
                <Link to="/services/gas-turbine-combustion" className="text-cyan-400 hover:text-cyan-300">combustion</Link>,{' '}
                <Link to="/services/test-cell-design" className="text-cyan-400 hover:text-cyan-300">test cells</Link> and{' '}
                <Link to="/services/industrial-ai" className="text-cyan-400 hover:text-cyan-300">industrial AI</Link>.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- Terms in plain words ---------- */}
      <section className="section-pad">
        <div className="container-site max-w-5xl">
          <SectionHeading
            eyebrow="The Terms"
            title="The terms, in plain words"
            subtitle="The full terms are shown again, with the amounts for your time, before you save a card."
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {plainTerms.map((t) => (
              <Reveal key={t.title} className="h-full">
                <div className="card h-full p-6">
                  <h3 className="text-base font-bold mb-2 flex items-start gap-2">
                    {t.title === 'What cannot be discussed' ? (
                      <ShieldAlert className="w-5 h-5 text-amber-300 shrink-0 mt-0.5" aria-hidden="true" />
                    ) : (
                      <CheckCircle2 className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                    )}
                    {t.title}
                  </h3>
                  <p className="text-slate-300 text-sm leading-relaxed">{t.desc}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- FAQ ---------- */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site max-w-4xl">
          <SectionHeading align="left" eyebrow="FAQ" title="Common questions" />
          <div className="space-y-8">
            {faqs.map((f) => (
              <Reveal key={f.q}>
                <h3 className="text-lg font-semibold mb-2">{f.q}</h3>
                <p className="text-slate-300 text-sm leading-relaxed">{f.a}</p>
              </Reveal>
            ))}
          </div>
          <Reveal className="mt-12">
            <a href="#book" className="btn-primary">
              Pick a time <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </a>
          </Reveal>
        </div>
      </section>
    </div>
  );
};

export default Consult;
