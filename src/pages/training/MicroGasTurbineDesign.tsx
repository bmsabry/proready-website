import React, { useEffect, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Award,
  BookOpen,
  Check,
  ChevronDown,
  CircuitBoard,
  Clock,
  FileSpreadsheet,
  Gauge,
  GraduationCap,
  Infinity as InfinityIcon,
  Layers,
  MonitorPlay,
  PlayCircle,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import { CTABand, Reveal, SectionHeading } from '../../components/ui';
import PayPalButtons, { fetchPaymentsConfig } from '../../components/PayPalButtons';
import {
  COURSE_SUBTITLE,
  MODULES,
  TOTAL_HOURS,
  TOTAL_VIDEO_PARTS,
} from './microGasTurbineCurriculum';
import FormatSwitcher from './FormatSwitcher';
import IndependenceNotice from './IndependenceNotice';
import CertificationSection from './CertificationSection';
import { formatIsoDate, snapshotStartLabel } from '../../data/courseSnapshot';

/* ---------------------------------------------------------------------------
   Micro Gas Turbine Design — on-demand course sales page.

   Distinct from the live-cohort pages: this product is bought once and kept
   for good, so the page sells a library rather than a seat. Curriculum is
   compiled in (see microGasTurbineCurriculum.ts) so the prerendered HTML
   carries the whole outline for search; only price/availability are live.
--------------------------------------------------------------------------- */

const PRODUCT_CODE = 'micro-gas-turbine-design';
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';
const CATALOG_ENDPOINT = API_BASE ? `${API_BASE}/api/academy/catalog/${PRODUCT_CODE}` : '';
const CHECKOUT_ENDPOINT = API_BASE ? `${API_BASE}/api/academy/checkout` : '';

// Shown until the API answers, and in the prerendered HTML.
const FALLBACK_PRICE_CENTS = 100000;

// The live-cohort edition of the same course, for the format chooser.
// Date fallback comes from the build-time snapshot; price fallback is the
// compiled-in list price until the runtime fetch lands.
const LIVE_COURSE_CODE = 'micro-gas-turbine-design-2026-10';
const LIVE_COURSE_ENDPOINT = API_BASE ? `${API_BASE}/api/courses/${LIVE_COURSE_CODE}` : '';
const FALLBACK_LIVE_PRICE_CENTS = 300000;
const DEFAULT_LIVE_COHORT_DATE = snapshotStartLabel(LIVE_COURSE_CODE, 'October 1, 2026');

const VIDEO_HOURS = 16;
const REFERENCE_ENGINE = '700 N';

function formatPrice(cents: number, currency = 'usd'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

/* ---------- What the buyer walks away able to do ---------- */
const OUTCOMES: { icon: React.ElementType; title: string; body: string }[] = [
  {
    icon: Gauge,
    title: 'Size a compressor stage from a thrust target',
    body: `Work from a ${REFERENCE_ENGINE} spec to impeller diameter, tip speed, blade count and backsweep, then check the slip factor and the pressure ratio you actually get, not the one you hoped for.`,
  },
  {
    icon: CircuitBoard,
    title: 'Design the combustor and its fuel schedule',
    body: 'Air split across primary, secondary and dilution zones; evaporative tube sizing; heat release rate, pattern factor and liner cooling; and a start schedule that lights reliably.',
  },
  {
    icon: Layers,
    title: 'Match a turbine to the compressor you designed',
    body: 'NGV and rotor meanline aerodynamics, blade loading, disc stress at speed and temperature, and the structural margin that decides whether the wheel survives.',
  },
  {
    icon: MonitorPlay,
    title: 'Read a compressor map and defend an operating line',
    body: 'Corrected flow and speed, surge and choke, surge margin against the 10–20% target, and what actually happens to the operating point when the throttle moves.',
  },
];

/* ---------- Everything that comes with it ---------- */
const INCLUDED: { icon: React.ElementType; title: string; body: string }[] = [
  {
    icon: PlayCircle,
    title: `${VIDEO_HOURS} hours of recorded sessions`,
    body: `${TOTAL_VIDEO_PARTS} lecture segments across five of the seven modules, delivered as taught: the derivations and the judgment calls, not a scripted read.`,
  },
  {
    icon: BookOpen,
    title: 'The complete slide decks',
    body: 'Every deck from the programme, viewable in the platform alongside the lecture it belongs to.',
  },
  {
    icon: FileSpreadsheet,
    title: 'Four design calculators',
    body: 'The same progressive spreadsheets used in the sessions: compressor, then compressor plus combustor, then the full engine including the turbine.',
  },
  {
    icon: Sparkles,
    title: 'Two interactive tools',
    body: 'A rotor training lab and a radial-compressor optimisation simulator you can run against your own numbers.',
  },
  {
    icon: GraduationCap,
    title: 'Module quizzes with real gates',
    body: 'Interactive assessments on five modules. Clear a module to open the next. That structure is what makes the material stick instead of washing over you.',
  },
  {
    icon: Award,
    title: 'Certificate on completion',
    body: 'Issued once every module gate and assessment is cleared, with a verification code anyone can check.',
  },
];

const FAQ: { q: string; a: string }[] = [
  {
    q: 'How long do I have access?',
    a: 'For as long as the platform exists. This is a one-time purchase, not a subscription. There is no renewal date and nothing expires. You can come back to any module years later.',
  },
  {
    q: 'Can I download the videos?',
    a: 'No. Lectures stream inside the platform and are not downloadable, which is what lets us put this much unpublished engine-design material online at all. Slide decks and the design spreadsheets are yours to work in.',
  },
  {
    q: 'What background do I need?',
    a: 'Undergraduate thermodynamics and fluid mechanics. The course starts from engine architecture and station numbering, so you do not need prior turbomachinery experience, but you do need to be comfortable with a control volume and an energy balance.',
  },
  {
    q: 'Is this theory or practice?',
    a: `Both, weighted toward practice. A ${REFERENCE_ENGINE} class reference engine runs through every module, so each piece of theory lands on the same machine. The worked examples use real dimensions and real speeds.`,
  },
  {
    q: 'Do I have to take the modules in order?',
    a: 'Yes. Each module unlocks when you clear the one before it. That is deliberate: the compressor work feeds the combustor, which feeds the turbine, and skipping ahead means solving for numbers you have not derived yet.',
  },
  {
    q: 'What if it is not for me?',
    a: 'Email within 14 days of purchase, tell us what missed, and we refund in full. No form to fill in.',
  },
];

/* ---------- Module accordion row ---------- */
const ModuleCard = ({ module, index }: { module: (typeof MODULES)[number]; index: number }) => {
  const [open, setOpen] = useState(false);
  const panelId = `module-panel-${module.code.toLowerCase()}`;

  return (
    <Reveal delay={index * 0.04}>
      <div className="card overflow-hidden">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={panelId}
          className="w-full flex items-start gap-4 p-5 sm:p-6 text-left hover:bg-slate-900/40 transition-colors"
        >
          <span className="shrink-0 mt-0.5 w-11 h-11 rounded-xl bg-cyan-500/10 border border-cyan-500/20 grid place-items-center font-mono text-sm text-cyan-400">
            {String(index + 1).padStart(2, '0')}
          </span>

          <span className="flex-1 min-w-0">
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-xs uppercase tracking-widest text-cyan-400">
                {module.code}
              </span>
              <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
                <Clock className="w-3.5 h-3.5" aria-hidden="true" />
                {module.hours} hrs
              </span>
              {module.videoParts > 0 && (
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
                  <PlayCircle className="w-3.5 h-3.5" aria-hidden="true" />
                  video
                </span>
              )}
              {module.hasQuiz && (
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
                  <GraduationCap className="w-3.5 h-3.5" aria-hidden="true" />
                  quiz
                </span>
              )}
            </span>
            <span className="block mt-1.5 text-base sm:text-lg font-semibold text-white leading-snug">
              {module.title}
            </span>
          </span>

          <ChevronDown
            className={`shrink-0 w-5 h-5 text-slate-500 transition-transform duration-200 ${
              open ? 'rotate-180' : ''
            }`}
            aria-hidden="true"
          />
        </button>

        {/* Rendered always so the prerendered HTML contains the full outline;
            visually collapsed until opened. */}
        <div id={panelId} hidden={!open} className="px-5 sm:px-6 pb-6 -mt-1">
          <p className="text-slate-300 leading-relaxed border-l-2 border-cyan-500/30 pl-4">
            {module.summary}
          </p>

          <div className="grid md:grid-cols-2 gap-6 mt-6">
            <div>
              <h4 className="text-xs font-mono uppercase tracking-widest text-slate-400 mb-3">
                By the end you can
              </h4>
              <ul className="space-y-2">
                {module.objectives.map((o) => (
                  <li key={o} className="flex gap-2.5 text-sm text-slate-300">
                    <Check className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                    <span>{o}</span>
                  </li>
                ))}
              </ul>
              {module.extras.length > 0 && (
                <>
                  <h4 className="text-xs font-mono uppercase tracking-widest text-slate-400 mt-6 mb-3">
                    Included with this module
                  </h4>
                  <ul className="flex flex-wrap gap-2">
                    {module.extras.map((e) => (
                      <li
                        key={e}
                        className="text-xs px-2.5 py-1 rounded-md bg-slate-900/70 border border-slate-800 text-slate-300"
                      >
                        {e}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>

            <div>
              <h4 className="text-xs font-mono uppercase tracking-widest text-slate-400 mb-3">
                Topics covered
              </h4>
              <ul className="space-y-1.5">
                {module.topics.map((t) => (
                  <li key={t} className="text-sm text-slate-400 leading-relaxed">
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </Reveal>
  );
};

/* ---------- Buy flow: PayPal-first, card as the fallback ----------
   Module-level on purpose: defined inside the page it would remount (and
   lose the buyer's typed email) on every parent re-render. The button
   expands in place into a small panel that collects email + name for the
   PayPal order; "Pay by card instead" keeps the existing Stripe path. When
   PayPal is not configured, the button goes straight to Stripe as before. */
const BuyFlow = ({
  full = false,
  owned,
  purchasable,
  price,
  paypalEnabled,
  checkoutState,
  onCardCheckout,
}: {
  full?: boolean;
  owned: boolean;
  purchasable: boolean;
  price: string;
  paypalEnabled: boolean;
  checkoutState: 'idle' | 'loading' | 'error';
  onCardCheckout: () => void;
}) => {
  const uid = useId();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [payError, setPayError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (owned) {
    return (
      <Link to="/learn" className={`btn-primary ${full ? 'w-full' : ''}`}>
        Go to your course <ArrowRight className="w-4 h-4" aria-hidden="true" />
      </Link>
    );
  }
  if (!purchasable) {
    return (
      <Link to="/contact" className={`btn-primary ${full ? 'w-full' : ''}`}>
        Ask about early access <ArrowRight className="w-4 h-4" aria-hidden="true" />
      </Link>
    );
  }

  const emailOk = /^\S+@\S+\.\S+$/.test(email.trim());

  const createOrder = async (): Promise<string> => {
    setPayError(null);
    const res = await fetch(`${API_BASE}/api/payments/recorded/paypal/create-order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_code: PRODUCT_CODE,
        email: email.trim(),
        full_name: fullName.trim(),
      }),
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

  const captureOrder = async (orderId: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/api/payments/recorded/paypal/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        order_id: orderId,
        product_code: PRODUCT_CODE,
        email: email.trim(),
        full_name: fullName.trim(),
      }),
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
    setDone(true);
    const next = typeof data.next === 'string' && data.next ? data.next : '/learn';
    window.setTimeout(() => {
      window.location.href = next;
    }, 1500);
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => (paypalEnabled ? setOpen(true) : onCardCheckout())}
        disabled={checkoutState === 'loading'}
        className={`btn-primary disabled:opacity-70 disabled:cursor-wait ${full ? 'w-full' : ''}`}
      >
        {checkoutState === 'loading' ? 'Opening checkout…' : `Get lifetime access for ${price}`}
        {checkoutState !== 'loading' && <ArrowRight className="w-4 h-4" aria-hidden="true" />}
      </button>
    );
  }

  if (done) {
    return (
      <div className={`rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-5 text-left ${full ? '' : 'max-w-md mx-auto'}`}>
        <p className="font-semibold text-white flex items-center gap-2">
          <Check className="w-4 h-4 text-cyan-400" aria-hidden="true" />
          Payment received
        </p>
        <p className="text-sm text-slate-300 mt-1.5">
          Taking you to your course. A sign-in link is also on its way to {email.trim()}.
        </p>
      </div>
    );
  }

  return (
    <div className={`rounded-xl border border-slate-700 bg-slate-950/60 p-5 text-left ${full ? '' : 'max-w-md mx-auto'}`}>
      <div className="flex items-baseline justify-between gap-3 mb-4">
        <p className="font-semibold text-white">Complete your purchase</p>
        <span className="font-mono text-sm text-cyan-300">{price}</span>
      </div>
      <div className="space-y-3 mb-4">
        <div className="space-y-1.5">
          <label htmlFor={`${uid}-email`} className="text-xs font-medium text-slate-300 uppercase tracking-wider">
            Email <span className="text-cyan-400" aria-hidden="true">*</span>
          </label>
          <input
            id={`${uid}-email`}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            autoComplete="email"
            className="w-full bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-400 transition-colors"
          />
          <p className="text-xs text-slate-500">Your course access and receipt go here.</p>
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${uid}-name`} className="text-xs font-medium text-slate-300 uppercase tracking-wider">
            Full name <span className="normal-case font-normal text-slate-500">(for your certificate)</span>
          </label>
          <input
            id={`${uid}-name`}
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Jane Doe"
            autoComplete="name"
            className="w-full bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-400 transition-colors"
          />
        </div>
      </div>
      {payError && (
        <p className="text-sm text-amber-300 mb-3" role="alert">
          {payError}
        </p>
      )}
      <p className="text-xs font-mono uppercase tracking-wider text-slate-300 mb-2">Pay with PayPal</p>
      <PayPalButtons createOrder={createOrder} onApprove={captureOrder} disabled={!emailOk} />
      {!emailOk && (
        <p className="text-xs text-slate-500 mt-1.5">Enter your email above to enable payment.</p>
      )}
      <button
        type="button"
        onClick={onCardCheckout}
        disabled={checkoutState === 'loading'}
        className="btn-secondary w-full mt-3 disabled:opacity-70 disabled:cursor-wait"
      >
        {checkoutState === 'loading' ? 'Opening checkout…' : 'Pay by card instead'}
      </button>
      <button type="button" onClick={() => setOpen(false)} className="btn-ghost mt-3 text-xs">
        Cancel
      </button>
    </div>
  );
};

const MicroGasTurbineDesign: React.FC = () => {
  const [priceCents, setPriceCents] = useState<number>(FALLBACK_PRICE_CENTS);
  const [currency, setCurrency] = useState<string>('usd');
  const [status, setStatus] = useState<'live' | 'draft'>('live');
  const [owned, setOwned] = useState(false);
  const [checkoutState, setCheckoutState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [paypalEnabled, setPaypalEnabled] = useState(false);
  // Live-cohort facts for the format chooser (price + next start date).
  const [livePriceCents, setLivePriceCents] = useState<number>(FALLBACK_LIVE_PRICE_CENTS);
  const [liveCohortDate, setLiveCohortDate] = useState<string>(DEFAULT_LIVE_COHORT_DATE);

  const price = formatPrice(priceCents, currency);
  const livePrice = formatPrice(livePriceCents);

  usePageMeta(
    'Micro Gas Turbine Design: On-Demand Course',
    `${TOTAL_HOURS} hours across 7 modules on designing a ${REFERENCE_ENGINE} single-shaft turbojet: architecture, centrifugal compressor, combustor, axial turbine, compressor maps, CFD and combustor analysis. Lifetime access.`,
    {
      image: 'https://proreadyengineer.com/Micro_Gas_Turbine_Design_Infographic.jpg',
      jsonLd: [
        {
          '@context': 'https://schema.org',
          '@type': 'Course',
          name: 'Micro Gas Turbine Design',
          image: 'https://proreadyengineer.com/Micro_Gas_Turbine_Design_Infographic.jpg',
          description: COURSE_SUBTITLE,
          provider: {
            '@type': 'Organization',
            name: 'ProReadyEngineer LLC',
            sameAs: 'https://proreadyengineer.com',
          },
          educationalLevel: 'Professional',
          teaches: MODULES.map((m) => m.title),
          hasCourseInstance: {
            '@type': 'CourseInstance',
            courseMode: 'online',
            courseWorkload: `PT${Math.round(TOTAL_HOURS)}H`,
          },
          offers: {
            '@type': 'Offer',
            category: 'Paid',
            price: (priceCents / 100).toFixed(2),
            priceCurrency: currency.toUpperCase(),
            availability: 'https://schema.org/InStock',
            url: 'https://proreadyengineer.com/training/micro-gas-turbine-design',
          },
        },
        {
          '@context': 'https://schema.org',
          '@type': 'FAQPage',
          mainEntity: FAQ.map((f) => ({
            '@type': 'Question',
            name: f.q,
            acceptedAnswer: { '@type': 'Answer', text: f.a },
          })),
        },
      ],
    }
  );

  // Live price/availability. Falls back silently to the compiled-in values
  // during prerender, local preview, or an API hiccup.
  useEffect(() => {
    if (!CATALOG_ENDPOINT) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(CATALOG_ENDPOINT, { credentials: 'include' });
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        if (typeof data.price_cents === 'number' && data.price_cents > 0) {
          setPriceCents(data.price_cents);
        }
        if (typeof data.currency === 'string') setCurrency(data.currency);
        if (data.status === 'draft') setStatus('draft');
        if (data.owned === true) setOwned(true);
      } catch {
        /* keep the compiled-in defaults */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Live-cohort price and next start date for the format chooser. Falls back
  // silently to the snapshot date + compiled-in price.
  useEffect(() => {
    if (!LIVE_COURSE_ENDPOINT) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(LIVE_COURSE_ENDPOINT, { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        if (typeof data.price_cents === 'number' && data.price_cents > 0) {
          setLivePriceCents(data.price_cents);
        }
        const startIso =
          Array.isArray(data.day_dates) && data.day_dates.length > 0
            ? data.day_dates[0]
            : data.start_date;
        if (typeof startIso === 'string' && startIso) {
          setLiveCohortDate(formatIsoDate(startIso));
        }
      } catch {
        /* keep the fallbacks */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Which providers the buy panel may offer. All-disabled until the API
  // answers, so the button falls back to the plain Stripe path meanwhile.
  useEffect(() => {
    if (!API_BASE) return;
    let cancelled = false;
    fetchPaymentsConfig().then((cfg) => {
      if (!cancelled) setPaypalEnabled(cfg.paypal_enabled);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const startCheckout = async () => {
    if (!CHECKOUT_ENDPOINT) return;
    setCheckoutState('loading');
    try {
      const res = await fetch(CHECKOUT_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_code: PRODUCT_CODE }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.url) {
        window.location.href = data.url;
        return;
      }
      setCheckoutState('error');
    } catch {
      setCheckoutState('error');
    }
  };

  const purchasable = status === 'live' && !!CHECKOUT_ENDPOINT;

  const buyProps = {
    owned,
    purchasable,
    price,
    paypalEnabled,
    checkoutState,
    onCardCheckout: startCheckout,
  };

  return (
    <div>
      {/* ---------------- Hero ---------------- */}
      <section className="relative pt-36 pb-12 lg:pt-44 overflow-hidden">
        <div className="hero-backdrop" />
        <div className="absolute inset-0 -z-10 bg-hero-radial" />

        <div className="container-site">
          <div className="grid lg:grid-cols-[1.35fr_1fr] gap-12 lg:gap-16 items-start">
            <div className="anim-hero">
              <span className="eyebrow mb-5">Self-paced · Lifetime access</span>
              <h1 className="text-4xl md:text-6xl font-bold tracking-tight mt-4 mb-6">
                Micro Gas Turbine <span className="text-gradient">Design</span>
              </h1>
              <p className="text-lg text-slate-300 leading-relaxed max-w-2xl">
                {COURSE_SUBTITLE}
              </p>
              <p className="mt-5 text-slate-400 leading-relaxed max-w-2xl">
                Seven modules and {TOTAL_HOURS} hours, recorded from the programme delivered to a
                national jet-engine development team. One {REFERENCE_ENGINE} class engine runs
                through every module, so the compressor you size in module two is the compressor the
                turbine has to match in module four.
              </p>

              {/* One course, two delivery formats — let the visitor switch */}
              <div className="mt-8 -mb-4">
                <FormatSwitcher
                  current="ondemand"
                  options={[
                    {
                      key: 'live',
                      title: 'Live Online Cohort',
                      price: `${livePrice} per seat`,
                      meta: `Next cohort ${liveCohortDate} · 7 days × 4 hours`,
                      to: '/training/micro-gas-turbine-design-live',
                    },
                    {
                      key: 'ondemand',
                      title: 'Self-Paced On-Demand',
                      price: `${price} one time`,
                      meta: 'Start today · lifetime access',
                      to: '/training/micro-gas-turbine-design',
                    },
                  ]}
                />
              </div>

              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-10 max-w-2xl">
                {[
                  { k: '7', v: 'Modules' },
                  { k: `${TOTAL_HOURS}`, v: 'Curriculum hours' },
                  { k: `${VIDEO_HOURS}h`, v: 'Recorded video' },
                  { k: '∞', v: 'Access' },
                ].map((s) => (
                  <div key={s.v} className="card px-4 py-4">
                    <dt className="font-display text-2xl md:text-3xl font-bold text-gradient tabular-nums">
                      {s.k}
                    </dt>
                    <dd className="mt-1 text-[11px] font-mono uppercase tracking-widest text-slate-400">
                      {s.v}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>

            {/* Purchase card */}
            <Reveal className="lg:sticky lg:top-28">
              <div className="card p-6 sm:p-7 relative overflow-hidden">
                <div
                  className="absolute -top-20 right-0 w-56 h-40 bg-cyan-500/10 blur-[80px] rounded-full pointer-events-none"
                  aria-hidden="true"
                />
                <div className="flex items-baseline gap-2">
                  <span className="font-display text-4xl font-bold text-white tabular-nums">
                    {price}
                  </span>
                  <span className="text-sm text-slate-400">one time</span>
                </div>
                <p className="mt-2 text-sm text-slate-400">
                  No subscription. No renewal. Yours for good.
                </p>

                <div className="mt-6">
                  <BuyFlow full {...buyProps} />
                  <p className="text-xs text-slate-400 mt-3">
                    Card or US bank account, securely through Stripe. Prefer Zelle or an
                    invoice?{' '}
                    <Link to="/contact" className="text-cyan-400 hover:text-cyan-300">
                      Contact us
                    </Link>
                    .
                  </p>
                </div>
                {checkoutState === 'error' && (
                  <p className="mt-3 text-sm text-amber-300" role="alert">
                    Checkout could not start. Please{' '}
                    <Link to="/contact" className="underline hover:text-amber-200">
                      contact us
                    </Link>{' '}
                    and we will send a payment link.
                  </p>
                )}

                <a href="#curriculum" className="btn-secondary w-full mt-3">
                  See the full curriculum
                </a>

                <ul className="mt-6 space-y-2.5 text-sm">
                  {[
                    { icon: InfinityIcon, t: 'Lifetime access, including updates' },
                    { icon: MonitorPlay, t: `${VIDEO_HOURS} hours of recorded sessions` },
                    { icon: FileSpreadsheet, t: 'Decks, calculators and interactive tools' },
                    { icon: GraduationCap, t: 'Module quizzes and progress tracking' },
                    { icon: Award, t: 'Certificate with public verification' },
                    { icon: ShieldCheck, t: '14-day refund, no forms' },
                  ].map(({ icon: Icon, t }) => (
                    <li key={t} className="flex gap-2.5 text-slate-300">
                      <Icon className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------------- Infographic showcase ---------------- */}
      <section className="pb-4">
        <div className="container-site">
          <Reveal>
            <img
              src="/Micro_Gas_Turbine_Design_Infographic.jpg"
              alt="Micro Gas Turbine Design: design a 700 N single-shaft turbojet end to end: engine architecture and gas path, centrifugal compressor, evaporative combustor, axial turbine, compressor maps and surge, turbomachinery CFD, and combustor analysis. Seven modules, 28.5 hours, 16 hours of video, lifetime access."
              className="w-full max-w-2xl mx-auto rounded-2xl border border-slate-800"
              width={1200}
              loading="lazy"
              decoding="async"
            />
          </Reveal>
        </div>
      </section>

      {/* ---------------- Outcomes ---------------- */}
      <section className="section-pad">
        <div className="container-site">
          <SectionHeading
            eyebrow="What you walk away with"
            title={
              <>
                Not a survey course. A{' '}
                <span className="text-gradient">design capability</span>.
              </>
            }
            subtitle="Most turbomachinery material stops at the equations. This one carries a single engine from architecture to a stability check, and asks you to do the arithmetic at every step."
          />
          <div className="grid md:grid-cols-2 gap-6">
            {OUTCOMES.map((o, i) => (
              <Reveal key={o.title} delay={i * 0.05}>
                <div className="card card-hover p-6 h-full">
                  <div className="w-11 h-11 rounded-xl bg-cyan-500/10 border border-cyan-500/20 grid place-items-center mb-4">
                    <o.icon className="w-5 h-5 text-cyan-400" aria-hidden="true" />
                  </div>
                  <h3 className="text-lg font-semibold text-white mb-2">{o.title}</h3>
                  <p className="text-slate-300 leading-relaxed">{o.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- Curriculum ---------------- */}
      <section id="curriculum" className="section-pad bg-slate-950/40 scroll-mt-24">
        <div className="container-site">
          <SectionHeading
            eyebrow="Curriculum"
            title={
              <>
                Seven modules, <span className="text-gradient">{TOTAL_HOURS} hours</span>
              </>
            }
            subtitle="Each module unlocks when you clear the one before it. Open any module below to see its objectives and full topic list."
          />
          <div className="space-y-4 max-w-4xl mx-auto">
            {MODULES.map((m, i) => (
              <ModuleCard key={m.code} module={m} index={i} />
            ))}
          </div>

          <Reveal className="max-w-4xl mx-auto mt-8">
            <div className="card p-6 flex flex-col sm:flex-row sm:items-center gap-5">
              <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/20 grid place-items-center shrink-0">
                <Sparkles className="w-6 h-6 text-cyan-400" aria-hidden="true" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-white">Finish with a design of your own</h3>
                <p className="text-slate-300 mt-1.5 leading-relaxed">
                  The closing exercise hands you a thrust target and asks for a stage: diameter,
                  speed, blade angle and count, with the physics behind each choice and the failure
                  mode you are most exposed to. It is marked against a published rubric.
                </p>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------------- What's included ---------------- */}
      <section className="section-pad">
        <div className="container-site">
          <SectionHeading
            eyebrow="What's included"
            title="Everything from the room, on your schedule"
            subtitle="The recordings are the sessions as they were taught, including the questions asked and the tangents worth keeping."
          />
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {INCLUDED.map((f, i) => (
              <Reveal key={f.title} delay={i * 0.04}>
                <div className="card card-hover p-6 h-full">
                  <f.icon className="w-6 h-6 text-cyan-400 mb-4" aria-hidden="true" />
                  <h3 className="font-semibold text-white mb-2">{f.title}</h3>
                  <p className="text-sm text-slate-300 leading-relaxed">{f.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- Instructor ---------------- */}
      <section className="section-pad bg-slate-950/40">
        <div className="container-site">
          <Reveal className="card p-8 md:p-12 max-w-4xl mx-auto">
            <span className="eyebrow mb-5">Who teaches it</span>
            <h2 className="text-3xl font-bold tracking-tight mt-3 mb-5">
              Taught by an engineer who has <span className="text-gradient">built and tested them</span>
            </h2>
            <p className="text-slate-300 leading-relaxed mb-4">
              Bassam Abdelnabi spent nineteen years in gas turbine combustion and test engineering,
              including at GE, with patents and published research behind him. The material here is
              the programme he delivered to a national jet-engine development team: the same decks,
              the same worked examples, the same reference engine.
            </p>
            <p className="text-slate-300 leading-relaxed">
              That matters most in the parts a textbook leaves out: which clearance actually works on
              a machined impeller, why a diffuser separates when the sizing rule said it would not,
              and what a test cell tells you that a simulation will not.
            </p>
            <div className="flex flex-wrap gap-3 mt-7">
              <Link to="/case-studies" className="btn-secondary">
                See the case studies
              </Link>
              <Link to="/testimonials" className="btn-ghost">
                What colleagues say <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------------- Certification ---------------- */}
      <CertificationSection courseTitle="Micro Gas Turbine Design" examinedPrice="$300" />

      {/* ---------------- How it works ---------------- */}
      <section className="section-pad">
        <div className="container-site">
          <SectionHeading eyebrow="How it works" title="From purchase to first lesson in a minute" />
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6 max-w-5xl mx-auto">
            {[
              { n: '01', t: 'Buy', d: 'Pay by card or US bank account through Stripe. Prefer Zelle? Contact us for an invoice.' },
              { n: '02', t: 'Check your email', d: 'A sign-in link lands within seconds. No password to invent or forget.' },
              { n: '03', t: 'Work through it', d: 'Watch, read, calculate. Progress saves as you go, on any device.' },
              { n: '04', t: 'Clear the gates', d: 'Pass each module assessment to unlock the next. Finish everything and your Certificate of Completion issues itself; go further with the instructor-examined credential.' },
            ].map((s, i) => (
              <Reveal key={s.n} delay={i * 0.05}>
                <div className="h-full">
                  <div className="font-mono text-sm text-cyan-400 mb-3">{s.n}</div>
                  <h3 className="font-semibold text-white mb-2">{s.t}</h3>
                  <p className="text-sm text-slate-300 leading-relaxed">{s.d}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- FAQ ---------------- */}
      <section className="section-pad bg-slate-950/40">
        <div className="container-site">
          <SectionHeading eyebrow="Questions" title="Before you buy" />
          <div className="max-w-3xl mx-auto space-y-4">
            {FAQ.map((f, i) => (
              <Reveal key={f.q} delay={i * 0.03}>
                <div className="card p-6">
                  <h3 className="font-semibold text-white mb-2">{f.q}</h3>
                  <p className="text-slate-300 leading-relaxed">{f.a}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- Close ---------------- */}
      <section className="section-pad">
        <div className="container-site">
          <Reveal className="card relative overflow-hidden text-center px-6 py-16 md:px-16 max-w-4xl mx-auto">
            <div
              className="absolute -top-24 left-1/2 -translate-x-1/2 w-[60%] h-48 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">
              Design the engine, not just the equations
            </h2>
            <p className="text-slate-300 max-w-2xl mx-auto mb-8">
              {TOTAL_HOURS} hours, seven modules, one reference engine, and the certificate at the
              end. {price} once, and it stays yours.
            </p>
            <div className="flex flex-col sm:flex-row justify-center gap-4">
              <BuyFlow {...buyProps} />
              <Link to="/contact" className="btn-secondary">
                Ask a question first
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      {/* Legal independence notice — shown on every course page */}
      <section className="pb-10">
        <div className="container-site">
          <IndependenceNotice />
        </div>
      </section>

      <CTABand
        title="Training a whole team?"
        subtitle="Team licences and private cohorts of this programme are available, including sessions tailored to your engine class."
        primaryLabel="Talk about team access"
        primaryTo="/contact"
        secondaryLabel="See all training"
        secondaryTo="/training"
      />
    </div>
  );
};

export default MicroGasTurbineDesign;
