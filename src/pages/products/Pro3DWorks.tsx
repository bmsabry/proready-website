import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Calculator,
  Check,
  CheckCircle2,
  ChevronDown,
  Cpu,
  CreditCard,
  Download,
  ExternalLink,
  FileCheck2,
  Layers,
  Lock,
  Monitor,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
} from 'lucide-react';
import { API_BASE } from '../../lib/academyApi';
import { apiErrorMessage } from '../../lib/apiError';
import { usePageMeta } from '../../lib/meta';
import highlightsData from '../../data/pro3dworks-highlights.json';
import Img from '../../components/Img';
import { Reveal, SectionHeading } from '../../components/ui';

type GalleryTab = {
  id: string;
  label: string;
  badge: string;
  src: string;
  alt: string;
  title: string;
  caption: string;
};

const GALLERY_TABS: GalleryTab[] = [
  {
    id: 'waterjet',
    label: 'Waterjet PDF → DWG',
    badge: 'AC1015 DWG + DXF',
    src: '/Pro3DWorks_Waterjet_Studio.png',
    alt: 'Pro3DWorks PDF Drawing to Waterjet DXF and DWG Studio showing extracted flange geometry, Topology Doctor warnings, and verified AC1015 DWG export',
    title: 'Shop-Verified PDF → DXF / DWG Conversion',
    caption:
      'Refits Bezier curves into true G1 biarcs/CIRCLEs, strips title blocks & hatching cleanly, calibrates scanned sheets with 2-point scaling, flags thin webs & tipping slugs, and cross-verifies every DWG with dual independent engines.',
  },
  {
    id: 'hero',
    label: '3D CAD & AP242 PMI',
    badge: '4-GiB OCCT Kernel',
    src: '/Pro3DWorks_Hero_Assembly.png',
    alt: 'Pro3DWorks v3.0 Dark Graphite workspace inspecting NIST STEP AP242 CAD geometry with semantic and graphical PMI/GD&T callouts',
    title: 'Zero-Cloud-Upload 3D STEP, IGES, SolidWorks & NX Inspection',
    caption:
      'Inspect exact B-Rep geometry locally in Studio Light or Graphite Dark themes. Read AP242 semantic + graphical GD&T datums cleanly alongside full assembly trees.',
  },
  {
    id: 'stackup',
    label: 'Tolerance Stack-Up',
    badge: 'NIST Verified',
    src: '/Pro3DWorks_Tolerance_Stackup.png',
    alt: 'Pro3DWorks 1D Tolerance Stack-Up panel running the NIST 2009 bolted assembly gap benchmark with Worst-Case, RSS, and Monte Carlo solvers',
    title: 'Deterministic Worst-Case, RSS & 20,000-Trial Monte Carlo Loops',
    caption:
      'Pull dimensions directly from AP242 PMI or enter manual loop contributors with verified math matching the NIST Syracuse 2009 bolted assembly benchmark.',
  },
  {
    id: 'machining',
    label: 'Machining & Native Bridge',
    badge: 'Local Native Helper',
    src: '/Pro3DWorks_Native_CAD.png',
    alt: 'Pro3DWorks CNC Machining Readiness workspace screening 6-axis tool access, deep pockets, and stock bounds in Graphite theme',
    title: '6-Axis CNC Readiness + Bundled SolidWorks & NX Native Bridge',
    caption:
      'Screen deep pockets, cutter reach, and stock bounding boxes locally—and install the guided Native Bridge wizard inside File to open .SLDPRT, .SLDASM, and Siemens NX .prt assemblies locally.',
  },
  {
    id: 'section',
    label: 'Triad Section & Caps',
    badge: 'Live Dh & Area',
    src: '/Pro3DWorks_Section_View.png',
    alt: 'Pro3DWorks 3-plane triad cross-section view with solid hatched polygon caps and live hydraulic diameter readouts',
    title: 'SolidWorks-Style 3-Plane Section Triad & Hatched Polygon Caps',
    caption:
      'Slide and tilt up to 3 independent section planes, compute live cut area and hydraulic diameter Dh, exclude fasteners cleanly, and export 1:1 2D SVG profiles.',
  },
  {
    id: 'printability',
    label: 'Printability & DFM',
    badge: 'Instant Export',
    src: '/Pro3DWorks_Printability_Audit.png',
    alt: 'Pro3DWorks 3D printability overhang and thin-wall diagnostic highlighting orientation tradeoffs',
    title: 'Overhang, Wall-Thickness & Self-Contained HTML Design Reviews',
    caption:
      'Catch unsupported overhangs, thin ribs, interference collisions, and mirror/duplicate BOM parts—then publish standalone HTML review packets anyone can open offline.',
  },
];

const COMPARISON_ROWS = [
  {
    feature: 'Vector + Scanned PDF → Verified .DWG & .DXF (G1 biarcs, OMAX/SendCutSend)',
    pro3d: true,
    legacyPdf: 'Partial (2D only)',
    cadSeat: 'Built-in ($1.9k+)',
    onlinePdf: 'Cloud risk / splines',
  },
  {
    feature: 'Open STEP, IGES, Parasolid, SolidWorks & NX locally (no cloud upload)',
    pro3d: true,
    legacyPdf: false,
    cadSeat: true,
    onlinePdf: false,
  },
  {
    feature: '3-Plane Triad Sectioning, Interference, Printability & 6-Axis CNC DFM',
    pro3d: true,
    legacyPdf: false,
    cadSeat: true,
    onlinePdf: false,
  },
  {
    feature: '1D Tolerance Stack-Up (Worst-Case, RSS, Monte Carlo) + AP242 PMI',
    pro3d: true,
    legacyPdf: false,
    cadSeat: 'Extra add-on',
    onlinePdf: false,
  },
  {
    feature: 'Waterjet Topology Doctor (thin webs, tipping slugs, cut/garnet estimate)',
    pro3d: true,
    legacyPdf: false,
    cadSeat: false,
    onlinePdf: false,
  },
  {
    feature: 'Founding Annual Price',
    pro3d: '$249 / yr ($29/mo)',
    legacyPdf: '$300–$500 / yr',
    cadSeat: '$1,500–$4,500+ / yr',
    onlinePdf: '$120–$240 / yr',
  },
];

const FAQS = [
  {
    q: 'Do I need a credit card to start the 15-day Pro trial?',
    a: 'No. Download Pro3DWorks-Setup-x64.exe, install on Windows 10/11 x64, and enter your email inside the desktop app. Your full 15-day Pro trial activates immediately without entering payment details.',
  },
  {
    q: 'What happens on Day 16 if I do not buy a license yet?',
    a: 'Pro3DWorks gracefully transitions to Free Basic 3D Viewer mode. You keep opening STEP, IGES, STL, GLB, and OBJ models, navigating the assembly tree, taking basic 3D measurements, and visually previewing PDFs in Waterjet Studio forever for free. Pro exports (.DWG/.DXF), native SolidWorks/NX decoding, Stack-Up, Photoreal, and AI Engineer pause until you activate a paid key.',
  },
  {
    q: 'How is money collected through Stripe and when am I charged?',
    a: 'Nothing is charged automatically during your trial. Whenever you choose a plan on this page or click Upgrade inside the app, Stripe Checkout securely collects payment upfront (card, Google Pay/Apple Pay/Link, or company Tax ID/VAT) for Pro Monthly ($29/mo), Pro Yearly ($249/yr), Shop Team 5-Pack ($149/mo or $1,390/yr), or Perpetual v3.x ($599 one-time). Subscriptions renew on Stripe unless cancelled anytime in the Customer Billing Portal.',
  },
  {
    q: 'How are SolidWorks (.SLDPRT/.SLDASM) and Siemens NX (.prt) viewers included?',
    a: 'The Windows desktop installer bundles the Pro3DWorks Native Bridge server and guided setup wizard (File → Setup SolidWorks & NX Native Viewer…). Because Pro3DWorks strictly honors third-party licensing, running that 1-click wizard prompts you once to review and accept NVIDIA usd-convert-cad terms (typing I ACCEPT) so native decoding stays 100% local on your PC without redistributing proprietary runtime files.',
  },
  {
    q: 'Can our air-gapped shop floor computer run Pro3DWorks offline?',
    a: 'Yes. Individual Pro subscriptions cache signed Ed25519 tokens locally with a 14-day offline grace window beyond each billing renewal. Shop / Team 5-Pack and Perpetual v3.x licenses also support downloadable .p3dwlic files imported directly offline inside Pro3DWorks without internet access on the shop floor PC.',
  },
];

export default function Pro3DWorksProduct() {
  usePageMeta(
    'Pro3DWorks v3.0 — 3D CAD Viewer, Waterjet PDF-to-DWG Studio & Native SolidWorks/NX',
    'Open SolidWorks, NX, STEP & IGES locally and convert shop PDFs into verified .DXF and .DWG cut files. Start a 15-day free Pro trial on Windows x64 — Founding Launch from $29/mo or $249/yr.',
    {
      image: 'https://proreadyengineer.com/Pro3DWorks_Hero_Assembly.png',
      jsonLd: {
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Pro3DWorks',
        softwareVersion: '3.0.0',
        operatingSystem: 'Windows 10, Windows 11 (x64)',
        applicationCategory: 'DesignApplication',
        offers: {
          '@type': 'Offer',
          price: '249.00',
          priceCurrency: 'USD',
          description: 'Founding Launch Pro Yearly license (15-day free trial included)',
        },
        publisher: {
          '@type': 'Organization',
          name: 'ProReadyEngineer LLC',
          url: 'https://proreadyengineer.com',
        },
      },
    },
  );

  const [activeTabId, setActiveTabId] = useState<string>('waterjet');
  const [annualBilling, setAnnualBilling] = useState<boolean>(true);
  const [buyerEmail, setBuyerEmail] = useState<string>('');
  const [busyPlan, setBusyPlan] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState<string>('');

  // Billing portal state
  const [portalInput, setPortalInput] = useState<string>('');
  const [portalBusy, setPortalBusy] = useState<boolean>(false);
  const [portalMessage, setPortalMessage] = useState<string>('');
  const [portalError, setPortalError] = useState<string>('');

  // ROI calculator inputs
  const [drawingsPerWeek, setDrawingsPerWeek] = useState<number>(8);
  const [minsSavedPerDrawing, setMinsSavedPerDrawing] = useState<number>(25);
  const [hourlyRate, setHourlyRate] = useState<number>(85);

  const [openFaq, setOpenFaq] = useState<number | null>(0);

  const activeTab = useMemo(
    () => GALLERY_TABS.find((t) => t.id === activeTabId) ?? GALLERY_TABS[0],
    [activeTabId],
  );

  const roi = useMemo(() => {
    const annualHours = Math.round(((drawingsPerWeek * 50 * minsSavedPerDrawing) / 60) * 10) / 10;
    const annualDollars = Math.round(annualHours * hourlyRate);
    const annualCost = 249;
    const multiple = annualDollars > 0 ? (annualDollars / annualCost).toFixed(1) : '0.0';
    const paybackDays =
      annualDollars > 0 ? Math.max(1, Math.round((annualCost / annualDollars) * 365)) : 365;
    return { annualHours, annualDollars, multiple, paybackDays };
  }, [drawingsPerWeek, minsSavedPerDrawing, hourlyRate]);

  async function startStripeCheckout(planCode: string) {
    setCheckoutError('');
    if (!API_BASE) {
      setCheckoutError('Online checkout service URL is not configured in this preview build.');
      return;
    }
    setBusyPlan(planCode);
    try {
      const payload: Record<string, unknown> = {
        product: 'pro3dworks',
        plan: planCode,
      };
      if (buyerEmail.trim()) payload.email = buyerEmail.trim();
      const res = await fetch(`${API_BASE}/api/software/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(apiErrorMessage(data, `Could not start checkout (${res.status}).`));
      }
      if (!data.url) {
        throw new Error('Checkout session URL missing from server response.');
      }
      window.location.href = String(data.url);
    } catch (e) {
      setCheckoutError(
        e instanceof Error ? e.message : 'Unable to start Stripe checkout. Please try again.',
      );
      setBusyPlan(null);
    }
  }

  async function openBillingPortal(e: React.FormEvent) {
    e.preventDefault();
    setPortalError('');
    setPortalMessage('');
    const val = portalInput.trim();
    if (!val) {
      setPortalError('Enter your license key (P3DW-...) or purchase email address.');
      return;
    }
    if (!API_BASE) {
      setPortalError('Billing portal service URL is not configured in this build.');
      return;
    }
    setPortalBusy(true);
    try {
      const isKey = val.toUpperCase().startsWith('P3DW-');
      const body = isKey ? { license_key: val.toUpperCase() } : { email: val.toLowerCase() };
      const res = await fetch(`${API_BASE}/api/software/billing-portal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(apiErrorMessage(data, `Request failed (${res.status}).`));
      }
      if (data.url) {
        window.open(String(data.url), '_blank', 'noopener');
        setPortalMessage('Opened your Stripe Customer Billing Portal in a new tab.');
      } else {
        setPortalMessage(
          data.message ||
            'If an active Stripe subscription exists for that email, your secure Billing Portal link has been emailed.',
        );
      }
    } catch (err) {
      setPortalError(err instanceof Error ? err.message : 'Could not reach Billing Portal.');
    } finally {
      setPortalBusy(false);
    }
  }

  const proPlanCode = annualBilling ? 'pro_yearly' : 'pro_monthly';
  const shopPlanCode = annualBilling ? 'shop_yearly' : 'shop_monthly';

  return (
    <div className="bg-slate-950 text-slate-50 min-h-screen">
      {/* Founding Launch Banner */}
      <div className="pt-20 bg-gradient-to-r from-cyan-950/90 via-slate-900 to-blue-950/90 border-b border-cyan-500/25">
        <div className="container-site py-2.5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs sm:text-sm text-center">
          <span className="inline-flex items-center gap-1.5 font-mono uppercase tracking-wider text-cyan-300 font-semibold">
            <Sparkles className="w-3.5 h-3.5" /> Founding Launch Promo
          </span>
          <span className="text-slate-200">
            Lock in <strong className="text-white">Pro at $29/mo</strong>{' '}
            <span className="line-through text-slate-400">$39</span> or{' '}
            <strong className="text-white">$249/yr</strong>{' '}
            <span className="line-through text-slate-400">$349</span> — includes full{' '}
            <strong className="text-emerald-300">15-Day No-Card Free Trial</strong>
          </span>
          <a
            href="#pricing"
            className="text-cyan-300 hover:text-cyan-200 underline underline-offset-4 font-semibold"
          >
            Claim Offer →
          </a>
        </div>
      </div>

      {/* Hero Split */}
      <section className="relative py-14 lg:py-24 overflow-hidden border-b border-slate-800/80">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(34,211,238,0.14),transparent_55%)]"
        />
        <div className="container-site relative grid lg:grid-cols-12 gap-10 lg:gap-12 items-center">
          <div className="lg:col-span-6 min-w-0">
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="eyebrow">
                <Monitor className="w-3.5 h-3.5" /> Windows 10/11 x64 Desktop App · v3.0.0
              </span>
              <span className="px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs font-mono">
                No Credit Card for Trial
              </span>
            </div>

            <h1 className="font-display text-4xl sm:text-5xl lg:text-5xl xl:text-[3.35rem] font-bold tracking-tight text-white leading-[1.08] mb-5">
              Convert Waterjet PDFs to Clean{' '}
              <span className="text-gradient">.DWG &amp; .DXF</span> — Plus SolidWorks &amp; NX
              Inspection Offline
            </h1>

            <p className="text-base sm:text-lg text-slate-300 leading-relaxed mb-7">
              Stop redrawing spline-riddled PDFs before cutting parts or paying $4,000+ per CAD seat just to inspect assemblies. Pro3DWorks v3 gives fabricators and mechanical engineers a single, fast local desktop workbench from{' '}
              <strong className="text-white">$29/mo or $249/yr</strong>.
            </p>

            <div className="flex flex-wrap gap-3 mb-7">
              <a
                href="/download/pro3dworks-installer"
                className="btn-primary text-base px-6 py-3.5"
              >
                <Download className="w-5 h-5" />
                Start 15-Day Free Trial (Windows x64)
              </a>
              <a href="#pricing" className="btn-secondary text-base px-6 py-3.5">
                See Plans &amp; Buy Key
                <ArrowRight className="w-4 h-4 text-cyan-400" />
              </a>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-sm text-slate-300">
              {[
                '15-day full Pro trial → Free Basic 3D Viewer forever',
                'Dual-verified Waterjet AC1015 DWG & SendCutSend R12 DXF',
                'Bundled SolidWorks & NX Native Bridge setup wizard',
                '4-GiB OCCT kernel · AP242 PMI · Stack-Up · BYOK AI',
              ].map((pt) => (
                <div key={pt} className="flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <span>{pt}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="lg:col-span-6 min-w-0">
            <div className="rounded-2xl border border-slate-700/80 bg-slate-900/90 p-3 sm:p-4 shadow-2xl shadow-cyan-950/30">
              <div className="rounded-xl overflow-hidden border border-slate-800">
                <Img
                  src="/Pro3DWorks_Waterjet_Studio.png"
                  alt="Pro3DWorks v3 Waterjet PDF to DXF and DWG Studio showing flange contour classification and verified AC1015 DWG export"
                  className="w-full h-auto block"
                  priority
                />
              </div>
              <div className="pt-3 px-1 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                <span className="font-mono text-cyan-300">
                  Waterjet Studio + 3D CAD Inspection Workbench
                </span>
                <span>17 MB Installer · Runs 100% Locally on Windows x64</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Interactive Tabbed Screenshot Showcase */}
      <section id="showcase" className="section-pad border-b border-slate-800/80">
        <div className="container-site">
          <SectionHeading
            eyebrow="See Inside Pro3DWorks v3"
            title="Real screenshots. Real NIST & fabrication test models."
            subtitle="Explore every module included in your 15-day free trial—from shop-floor waterjet DWG preparation to deterministic ASME/NIST 1D tolerance stack-ups."
          />

          <div className="flex flex-wrap justify-center gap-2 mb-6" role="tablist">
            {GALLERY_TABS.map((tab) => {
              const active = tab.id === activeTab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveTabId(tab.id)}
                  className={`px-3.5 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    active
                      ? 'bg-cyan-500 text-slate-950 border-cyan-400 font-semibold shadow-glow-cyan'
                      : 'bg-slate-900/70 text-slate-300 border-slate-800 hover:border-slate-600 hover:text-white'
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className="card p-4 sm:p-6 bg-slate-900/70 border-slate-800">
            <div className="rounded-xl overflow-hidden border border-slate-800 bg-slate-950">
              <Img
                src={activeTab.src}
                alt={activeTab.alt}
                className="w-full h-auto block"
              />
            </div>
            <div className="mt-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2.5 mb-1.5">
                  <span className="px-2.5 py-0.5 rounded-full bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 text-xs font-mono">
                    {activeTab.badge}
                  </span>
                  <h3 className="text-lg sm:text-xl font-bold text-white">{activeTab.title}</h3>
                </div>
                <p className="text-sm sm:text-base text-slate-300 max-w-4xl leading-relaxed">
                  {activeTab.caption}
                </p>
              </div>
              <a
                href="/download/pro3dworks-installer"
                className="btn-secondary shrink-0 text-sm py-2.5 px-4"
              >
                <Download className="w-4 h-4 text-cyan-400" />
                Try This in 15-Day Trial
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Three Deep Capability Spotlights */}
      <section className="section-pad border-b border-slate-800/80 bg-slate-900/20">
        <div className="container-site space-y-16">
          <SectionHeading
            eyebrow="Why Teams Switch to Pro3DWorks"
            title="Three engineering engines in one offline desktop app"
            subtitle="Designed to solve the exact bottlenecks machine shops, waterjet operators, and hardware review teams fight every week."
          />

          {/* Spotlight 1: Waterjet */}
          <Reveal className="grid lg:grid-cols-12 gap-8 items-center">
            <div className="lg:col-span-5 min-w-0">
              <div className="eyebrow mb-3">
                <Wrench className="w-3.5 h-3.5" /> Built for Waterjet &amp; Laser Shops
              </div>
              <h3 className="text-2xl sm:text-3xl font-bold text-white mb-4">
                PDF Drawing → Waterjet .DXF &amp; .DWG Studio
              </h3>
              <p className="text-slate-300 leading-relaxed mb-5">
                Generic PDF converters dump thousands of exploded Bezier segments, dimension arrows, borders, and cross-hatch noise that crash CAM nesting software. Pro3DWorks cleans and refits paths specifically for abrasive waterjet cutting:
              </p>
              <ul className="space-y-2.5 text-sm text-slate-200">
                {[
                  'True G1 biarc / ARC / CIRCLE fitting instead of faceted polygon chords',
                  'Automatic removal of title blocks, hidden OCG layers, hatch fills & dimension callouts',
                  'Exploded dash joining, Overkill deduping & gap healing down to configurable tolerance',
                  'Raster scan auto-deskew & 2-point reference calibration for scanned shop prints',
                  'Topology Doctor flags thin webs, sharp pierce corners, self-intersections & tipping slugs',
                  'OMAX Q1-Q5 ACI color mapping & SendCutSend R12 DXF presets + live garnet/cut estimator',
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2.5">
                    <Check className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="lg:col-span-7 min-w-0">
              <div className="card p-3 bg-slate-900/80">
                <Img
                  src="/Pro3DWorks_Waterjet_Studio.png"
                  alt="Waterjet Studio dual verified AC1015 DWG export and pre-flight QA panel"
                  className="w-full h-auto rounded-xl"
                />
              </div>
            </div>
          </Reveal>

          {/* Spotlight 2: SolidWorks & NX Native Bridge */}
          <Reveal className="grid lg:grid-cols-12 gap-8 items-center">
            <div className="lg:col-span-7 min-w-0 order-2 lg:order-1">
              <div className="card p-3 bg-slate-900/80">
                <Img
                  src="/Pro3DWorks_Native_CAD.png"
                  alt="CNC Machining Readiness screening and local native SolidWorks/NX environment in Graphite theme"
                  className="w-full h-auto rounded-xl"
                />
              </div>
            </div>
            <div className="lg:col-span-5 min-w-0 order-1 lg:order-2">
              <div className="eyebrow mb-3">
                <Cpu className="w-3.5 h-3.5" /> SolidWorks &amp; Siemens NX Included Setup
              </div>
              <h3 className="text-2xl sm:text-3xl font-bold text-white mb-4">
                Bundled Local SolidWorks &amp; NX Native Viewer — Zero Cloud Leaks
              </h3>
              <p className="text-slate-300 leading-relaxed mb-5">
                Every Pro3DWorks v3 Windows installer ships the local CAD Translation Bridge inside the app bundle. Open client assemblies directly on your workstation:
              </p>
              <ul className="space-y-2.5 text-sm text-slate-200">
                {[
                  'Direct browser-kernel support for STEP AP203/214/242, IGES, BREP, Parasolid, STL, 3MF & GLB (4-GiB WASM ceiling)',
                  'Legacy SolidWorks (.SLDPRT/.SLDASM) saved-display preview works right out of the box',
                  'File → Setup SolidWorks & NX Native Viewer configures NVIDIA usd-convert-cad locally with your explicit opt-in consent',
                  'Supports modern & legacy SolidWorks parts/assemblies plus Siemens NX .prt natively on localhost with cryptographic session tokens',
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2.5">
                    <Check className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Reveal>

          {/* Spotlight 3: Full Inspection Suite */}
          <Reveal className="grid lg:grid-cols-12 gap-8 items-center">
            <div className="lg:col-span-5 min-w-0">
              <div className="eyebrow mb-3">
                <Layers className="w-3.5 h-3.5" /> Quantitative Engineering QA
              </div>
              <h3 className="text-2xl sm:text-3xl font-bold text-white mb-4">
                1D Tolerance Stack-Up, AP242 PMI, 3-Plane Section &amp; Design Review Packs
              </h3>
              <p className="text-slate-300 leading-relaxed mb-5">
                Designed for real hardware review gates—so procurement, DFM, and metrology teams get hard numbers without tying up full MCAD licenses:
              </p>
              <ul className="space-y-2.5 text-sm text-slate-200">
                {[
                  'NIST-benchmarked 1D linear loop stack-up solver: Worst-Case, RSS, and 20k+ Monte Carlo',
                  'AP242 semantic & graphical GD&T datum isolation with explicit face/entity provenance',
                  '3-plane Triad Sectioning with solid hatched caps, cut area & hydraulic diameter Dh',
                  '3D Printability, 6-axis CNC reachability, Draft angle & Collision interference audits',
                  'Export self-contained offline HTML review reports & Bring-Your-Own-Key AI Engineer workflows',
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2.5">
                    <Check className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="lg:col-span-7 min-w-0">
              <div className="card p-3 bg-slate-900/80">
                <Img
                  src="/Pro3DWorks_Tolerance_Stackup.png"
                  alt="Pro3DWorks 1D Tolerance Stack-Up NIST benchmark workspace"
                  className="w-full h-auto rounded-xl"
                />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ROI Calculator + Competitor Comparison */}
      <section id="roi" className="section-pad border-b border-slate-800/80">
        <div className="container-site grid lg:grid-cols-12 gap-10 items-start">
          {/* Interactive ROI Calculator */}
          <Reveal className="lg:col-span-5 min-w-0 card p-6 sm:p-7 bg-slate-900/80 border-cyan-500/25">
            <div className="flex items-center gap-2 text-cyan-300 font-mono text-xs uppercase tracking-widest mb-2">
              <Calculator className="w-4 h-4" /> Shop &amp; Engineering ROI Calculator
            </div>
            <h3 className="text-2xl font-bold text-white mb-2">
              How fast does Pro3DWorks pay for itself?
            </h3>
            <p className="text-sm text-slate-300 mb-6">
              Adjust your weekly shop drawing load to see annual savings vs. our $249/yr Pro Yearly license:
            </p>

            <div className="space-y-5">
              <label className="block">
                <div className="flex justify-between text-sm mb-1.5">
                  <span className="text-slate-200">PDF drawings prepped / CAD checks per week</span>
                  <span className="font-mono font-bold text-cyan-300">{drawingsPerWeek}</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={50}
                  value={drawingsPerWeek}
                  onChange={(e) => setDrawingsPerWeek(Number(e.target.value))}
                  className="w-full accent-cyan-400 cursor-pointer"
                />
              </label>

              <label className="block">
                <div className="flex justify-between text-sm mb-1.5">
                  <span className="text-slate-200">Minutes saved per drawing vs manual cleanup</span>
                  <span className="font-mono font-bold text-cyan-300">{minsSavedPerDrawing} min</span>
                </div>
                <input
                  type="range"
                  min={10}
                  max={60}
                  step={5}
                  value={minsSavedPerDrawing}
                  onChange={(e) => setMinsSavedPerDrawing(Number(e.target.value))}
                  className="w-full accent-cyan-400 cursor-pointer"
                />
              </label>

              <label className="block">
                <div className="flex justify-between text-sm mb-1.5">
                  <span className="text-slate-200">Burdened programmer / engineer rate</span>
                  <span className="font-mono font-bold text-cyan-300">${hourlyRate}/hr</span>
                </div>
                <input
                  type="range"
                  min={40}
                  max={200}
                  step={5}
                  value={hourlyRate}
                  onChange={(e) => setHourlyRate(Number(e.target.value))}
                  className="w-full accent-cyan-400 cursor-pointer"
                />
              </label>
            </div>

            <div className="mt-6 pt-5 border-t border-slate-800 grid grid-cols-3 gap-3 text-center">
              <div className="rounded-xl bg-slate-950/80 border border-slate-800 p-3">
                <div className="text-xs text-slate-400">Hours Saved / Yr</div>
                <div className="text-xl font-bold text-white font-mono mt-1">
                  {roi.annualHours.toLocaleString()}h
                </div>
              </div>
              <div className="rounded-xl bg-slate-950/80 border border-cyan-500/30 p-3">
                <div className="text-xs text-slate-400">Annual Savings</div>
                <div className="text-xl font-bold text-cyan-300 font-mono mt-1">
                  ${roi.annualDollars.toLocaleString()}
                </div>
              </div>
              <div className="rounded-xl bg-slate-950/80 border border-emerald-500/30 p-3">
                <div className="text-xs text-slate-400">Payback</div>
                <div className="text-xl font-bold text-emerald-300 font-mono mt-1">
                  ~{roi.paybackDays}d ({roi.multiple}×)
                </div>
              </div>
            </div>
          </Reveal>

          {/* Competitor Comparison Table */}
          <Reveal className="lg:col-span-7 min-w-0 w-full">
            <h3 className="text-2xl font-bold text-white mb-2">
              How Pro3DWorks compares against legacy alternatives
            </h3>
            <p className="text-sm text-slate-300 mb-5">
              One focused tool replacing both standalone PDF-to-DWG utilities and expensive viewer-only CAD seat renewals.
            </p>
            <div className="overflow-x-auto max-w-full card">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-900/95 border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                  <tr>
                    <th className="py-3.5 px-4">Capability</th>
                    <th className="py-3.5 px-4 text-cyan-300">Pro3DWorks v3</th>
                    <th className="py-3.5 px-4">PDF Utilities</th>
                    <th className="py-3.5 px-4">MCAD Seat</th>
                    <th className="py-3.5 px-4">Web Converters</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70 text-slate-300">
                  {COMPARISON_ROWS.map((row) => (
                    <tr key={row.feature} className="hover:bg-slate-900/40">
                      <td className="py-3 px-4 font-medium text-slate-200">{row.feature}</td>
                      <td className="py-3 px-4 font-semibold text-emerald-300">
                        {row.pro3d === true ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : row.pro3d}
                      </td>
                      <td className="py-3 px-4 text-slate-400">
                        {row.legacyPdf === false ? <X className="w-4 h-4 text-slate-600" /> : row.legacyPdf}
                      </td>
                      <td className="py-3 px-4 text-slate-400">
                        {row.cadSeat === true ? <Check className="w-4 h-4 text-slate-400" /> : row.cadSeat}
                      </td>
                      <td className="py-3 px-4 text-slate-400">
                        {row.onlinePdf === false ? <X className="w-4 h-4 text-slate-600" /> : row.onlinePdf}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Reveal>
        </div>
      </section>

      {/* 4-Step Visual Trial & Stripe Payment Flow */}
      <section id="trial-flow" className="section-pad border-b border-slate-800/80 bg-slate-900/25">
        <div className="container-site">
          <SectionHeading
            eyebrow="Zero-Risk Licensing & Billing Flow"
            title="15-Day Free Trial first. Pay via Stripe only when convinced."
            subtitle="We designed our billing timeline to be transparent for both individual engineers and corporate procurement teams."
          />

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {[
              {
                step: '01 · Day 0',
                title: 'Install Windows x64 App',
                body: 'Download Pro3DWorks-Setup-x64.exe (~17 MB) with zero credit card. Bundled local SolidWorks & NX Native Bridge setup sits right in the File menu.',
              },
              {
                step: '02 · Days 1–15',
                title: '15-Day Full Pro Trial',
                body: 'Enter your work email inside the app to activate a cryptographic Ed25519 trial token tied to your PC. Export unlimited Waterjet DXF/DWGs & run every Pro audit.',
              },
              {
                step: '03 · Anytime',
                title: 'Stripe Checkout + Key Delivery',
                body: 'When ready, pick Pro, Shop Team, or Perpetual below (or click Upgrade in-app). Stripe charges safely at checkout, emails your P3DW- key immediately, and unlocks 1-click activation.',
              },
              {
                step: '04 · Day 16 Fallback',
                title: 'Free Basic 3D Viewer Forever',
                body: 'Never lose access to your work: if a trial ends without purchase, Pro3DWorks smoothly switches to Free Basic 3D Viewing & PDF preview—or upgrade anytime via Stripe.',
              },
            ].map((card) => (
              <Reveal key={card.step} className="card p-6 bg-slate-900/70">
                <div className="text-xs font-mono uppercase tracking-widest text-cyan-400 mb-2">
                  {card.step}
                </div>
                <h3 className="text-lg font-bold text-white mb-2">{card.title}</h3>
                <p className="text-sm text-slate-300 leading-relaxed">{card.body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing & Stripe Checkout Section */}
      <section id="pricing" className="section-pad border-b border-slate-800/80">
        <div className="container-site">
          <SectionHeading
            eyebrow="Simple Founding Pricing"
            title="Start free for 15 days, or unlock Pro now"
            subtitle="Every paid license is collected securely through Stripe with Tax ID / VAT invoice collection, promo code support, and instant Ed25519 key delivery."
          />

          {/* Billing Interval Toggle + Optional Email Pre-fill */}
          <div className="max-w-2xl mx-auto mb-10 flex flex-col items-center gap-4">
            <div className="inline-flex items-center p-1 rounded-xl bg-slate-900 border border-slate-800">
              <button
                type="button"
                onClick={() => setAnnualBilling(true)}
                className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
                  annualBilling
                    ? 'bg-cyan-500 text-slate-950'
                    : 'text-slate-300 hover:text-white'
                }`}
              >
                Annual (Save ~28%)
              </button>
              <button
                type="button"
                onClick={() => setAnnualBilling(false)}
                className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
                  !annualBilling
                    ? 'bg-cyan-500 text-slate-950'
                    : 'text-slate-300 hover:text-white'
                }`}
              >
                Monthly Flexible
              </button>
            </div>

            <div className="w-full max-w-md">
              <label className="block text-xs text-slate-400 mb-1 text-center">
                Optional receipt &amp; license key delivery email (pre-fills Stripe Checkout)
              </label>
              <input
                type="email"
                value={buyerEmail}
                onChange={(e) => setBuyerEmail(e.target.value)}
                placeholder="engineer@yourshop.com"
                className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3.5 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>

            {checkoutError && (
              <div className="w-full rounded-xl border border-amber-500/40 bg-amber-500/10 text-amber-200 text-sm px-4 py-3 text-center">
                {checkoutError}
              </div>
            )}
          </div>

          {/* 4-Column Pricing Cards */}
          <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-6 items-stretch">
            {/* Free Basic 3D Viewer */}
            <div className="card p-6 flex flex-col justify-between bg-slate-900/50">
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-slate-400">
                  Day 16+ Fallback
                </span>
                <h3 className="text-xl font-bold text-white mt-1">Free Basic 3D Viewer</h3>
                <div className="mt-4 flex items-baseline gap-2">
                  <span className="text-4xl font-bold text-white">$0</span>
                  <span className="text-sm text-slate-400">forever after 15d trial</span>
                </div>
                <p className="text-xs text-slate-400 mt-2 mb-5">
                  Included in every installer with zero card required.
                </p>
                <ul className="space-y-2.5 text-sm text-slate-300 mb-6">
                  {[
                    'Includes full 15-day Pro trial on Day 1',
                    'Open STEP, IGES, STL, GLB, OBJ models offline',
                    'Orbit, zoom, fit, tree isolate & basic distance measure',
                    'Waterjet PDF visual preview & QA inspection',
                  ].map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <Check className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <a
                href="/download/pro3dworks-installer"
                className="btn-secondary w-full text-sm py-2.5"
              >
                <Download className="w-4 h-4 text-cyan-400" />
                Download Free Trial
              </a>
            </div>

            {/* Pro Individual (Popular) */}
            <div className="card p-6 flex flex-col justify-between bg-gradient-to-b from-slate-900 via-slate-900 to-cyan-950/30 border-cyan-500/50 ring-1 ring-cyan-500/25 relative">
              <div className="absolute -top-3 right-5 px-3 py-0.5 rounded-full bg-cyan-500 text-slate-950 text-xs font-bold uppercase tracking-wider">
                Most Popular · Founding
              </div>
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-cyan-300">
                  Solo Engineer &amp; Shop
                </span>
                <h3 className="text-xl font-bold text-white mt-1">Pro Individual</h3>
                <div className="mt-4 flex items-baseline gap-2">
                  <span className="text-4xl font-bold text-white">
                    ${annualBilling ? '249' : '29'}
                  </span>
                  <span className="text-sm text-slate-300">
                    /{annualBilling ? 'year' : 'month'}
                  </span>
                  <span className="text-sm text-slate-400 line-through">
                    ${annualBilling ? '349' : '39'}
                  </span>
                </div>
                <p className="text-xs text-cyan-200/80 mt-2 mb-5">
                  Up to 3 workstations · 14-day offline renewal grace
                </p>
                <ul className="space-y-2.5 text-sm text-slate-200 mb-6">
                  {[
                    'Unlimited Waterjet PDF → verified .DXF & .DWG exports',
                    'OMAX Q1–Q5 & SendCutSend R12 presets + Topology Doctor',
                    'Bundled SolidWorks (.SLDPRT/.SLDASM) & NX (.prt) bridge',
                    '3-Plane Section Pro, Interference, CNC, Printability & Draft',
                    'AP242 PMI, 1D Stack-Up, 4K Render & BYOK AI Engineer',
                    'Transfer seats anytime in Desktop License Manager',
                  ].map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <button
                type="button"
                disabled={busyPlan !== null}
                onClick={() => void startStripeCheckout(proPlanCode)}
                className="btn-primary w-full text-sm py-2.5 disabled:opacity-60"
              >
                <CreditCard className="w-4 h-4" />
                {busyPlan === proPlanCode
                  ? 'Redirecting to Stripe…'
                  : `Buy Pro (${annualBilling ? '$249/yr' : '$29/mo'})`}
              </button>
            </div>

            {/* Shop / Team 5-Pack */}
            <div className="card p-6 flex flex-col justify-between bg-slate-900/75">
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-blue-300">
                  Multi-Seat Fabrication Shop
                </span>
                <h3 className="text-xl font-bold text-white mt-1">Shop / Team 5-Pack</h3>
                <div className="mt-4 flex items-baseline gap-2">
                  <span className="text-4xl font-bold text-white">
                    ${annualBilling ? '1,390' : '149'}
                  </span>
                  <span className="text-sm text-slate-300">
                    /{annualBilling ? 'year' : 'month'}
                  </span>
                </div>
                <p className="text-xs text-slate-300 mt-2 mb-5">
                  5 active workstations · Air-gapped .p3dwlic option
                </p>
                <ul className="space-y-2.5 text-sm text-slate-200 mb-6">
                  {[
                    'All Pro features unlocked across 5 shop & engineering PCs',
                    'Request signed offline .p3dwlic files for disconnected CNC/waterjet PCs',
                    'Single Stripe invoice & VAT/Tax-ID receipt for accounting',
                    'Shared review reports & BOM workflows across programmers',
                    'Priority engineering support response',
                  ].map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <CheckCircle2 className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <button
                type="button"
                disabled={busyPlan !== null}
                onClick={() => void startStripeCheckout(shopPlanCode)}
                className="btn-secondary w-full text-sm py-2.5 border-blue-500/40 hover:border-blue-400 disabled:opacity-60"
              >
                <CreditCard className="w-4 h-4 text-blue-400" />
                {busyPlan === shopPlanCode
                  ? 'Redirecting to Stripe…'
                  : `Buy Shop 5-Pack (${annualBilling ? '$1,390/yr' : '$149/mo'})`}
              </button>
            </div>

            {/* Perpetual v3.x */}
            <div className="card p-6 flex flex-col justify-between bg-slate-900/75 border-amber-500/30">
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-amber-300">
                  Own v3.x Outright
                </span>
                <h3 className="text-xl font-bold text-white mt-1">Perpetual v3.x License</h3>
                <div className="mt-4 flex items-baseline gap-2">
                  <span className="text-4xl font-bold text-white">$599</span>
                  <span className="text-sm text-slate-300">one-time</span>
                </div>
                <p className="text-xs text-amber-200/80 mt-2 mb-5">
                  No recurring subscription · 3 workstations + 1 yr updates
                </p>
                <ul className="space-y-2.5 text-sm text-slate-200 mb-6">
                  {[
                    'Pay once via Stripe — own Pro3DWorks v3.x permanently',
                    'All Pro Waterjet, SolidWorks/NX, PMI, Stack-Up & AI tools',
                    'Includes 1 full year of v3.x updates & offline .p3dwlic support',
                    'Keep running v3.x offline indefinitely with zero annual fees',
                  ].map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <CheckCircle2 className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <button
                type="button"
                disabled={busyPlan !== null}
                onClick={() => void startStripeCheckout('perpetual')}
                className="btn-secondary w-full text-sm py-2.5 border-amber-500/40 hover:border-amber-400 disabled:opacity-60"
              >
                <ShieldCheck className="w-4 h-4 text-amber-400" />
                {busyPlan === 'perpetual' ? 'Redirecting to Stripe…' : 'Buy Perpetual ($599)'}
              </button>
            </div>
          </div>

          {/* Manage Billing / Customer Portal Box */}
          <div
            id="manage-license"
            className="mt-10 card p-6 sm:p-7 bg-slate-900/60 border-slate-800 max-w-4xl mx-auto"
          >
            <div className="grid md:grid-cols-12 gap-5 items-center">
              <div className="md:col-span-6 min-w-0">
                <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-cyan-400 mb-1">
                  <Lock className="w-3.5 h-3.5" /> Stripe Customer Billing Portal
                </div>
                <h3 className="text-lg font-bold text-white">
                  Already purchased? Manage invoices, cards, or cancel anytime.
                </h3>
                <p className="text-xs sm:text-sm text-slate-300 mt-1">
                  Enter your <code className="text-cyan-300">P3DW-XXXX-…</code> key for an immediate link, or enter your purchase email to receive a one-click portal link securely in your inbox.
                </p>
              </div>
              <form onSubmit={openBillingPortal} className="md:col-span-6 min-w-0 flex flex-col sm:flex-row gap-2.5">
                <input
                  type="text"
                  value={portalInput}
                  onChange={(e) => setPortalInput(e.target.value)}
                  placeholder="P3DW-XXXX-... or billing@company.com"
                  className="flex-1 rounded-lg bg-slate-950 border border-slate-700 px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
                />
                <button
                  type="submit"
                  disabled={portalBusy}
                  className="btn-secondary text-sm py-2.5 px-4 shrink-0 disabled:opacity-60"
                >
                  <ExternalLink className="w-4 h-4 text-cyan-400" />
                  {portalBusy ? 'Sending…' : 'Billing Portal'}
                </button>
              </form>
            </div>
            {portalMessage && (
              <p className="mt-3 text-sm text-emerald-300 flex items-center gap-2">
                <FileCheck2 className="w-4 h-4 shrink-0" /> {portalMessage}
              </p>
            )}
            {portalError && <p className="mt-3 text-sm text-red-300">{portalError}</p>}
          </div>
        </div>
      </section>

      {/* What's New in v3.0.0 Strip */}
      <section className="section-pad border-b border-slate-800/80 bg-slate-900/20">
        <div className="container-site">
          <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
            <div>
              <span className="eyebrow mb-3">Release Notes · v{highlightsData.version}</span>
              <h2 className="text-2xl sm:text-3xl font-bold text-white">
                {highlightsData.name}
              </h2>
              <p className="text-sm sm:text-base text-slate-300 max-w-3xl mt-2">
                {highlightsData.summary}
              </p>
            </div>
            <Link to="/products" className="btn-ghost shrink-0">
              ← Back to Products Catalog
            </Link>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {highlightsData.highlights.map((h) => (
              <div key={h.title} className="card p-5 bg-slate-900/70">
                <h3 className="text-base font-bold text-cyan-300 mb-2">{h.title}</h3>
                <p className="text-sm text-slate-300 leading-relaxed">{h.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ Accordion */}
      <section className="section-pad">
        <div className="container-site max-w-4xl">
          <SectionHeading
            eyebrow="Questions & Procurement"
            title="Licensing, Offline Workstations & Native CAD FAQ"
          />

          <div className="space-y-3">
            {FAQS.map((item, idx) => {
              const open = openFaq === idx;
              return (
                <div key={item.q} className="card bg-slate-900/70 overflow-hidden">
                  <button
                    type="button"
                    aria-expanded={open}
                    onClick={() => setOpenFaq(open ? null : idx)}
                    className="w-full px-5 py-4 flex items-center justify-between gap-4 text-left"
                  >
                    <span className="font-semibold text-white text-sm sm:text-base">{item.q}</span>
                    <ChevronDown
                      className={`w-5 h-5 text-cyan-400 shrink-0 transition-transform ${
                        open ? 'rotate-180' : ''
                      }`}
                    />
                  </button>
                  {open && (
                    <div className="px-5 pb-4 text-sm text-slate-300 leading-relaxed border-t border-slate-800/70 pt-3">
                      {item.a}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}
