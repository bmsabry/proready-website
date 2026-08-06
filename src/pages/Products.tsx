import React, { useEffect, useState } from 'react';
import {
  Download, CheckCircle2, ShieldCheck, Sparkles, Boxes, Camera, Ruler, Heart, CircleDollarSign,
} from 'lucide-react';
import { Reveal, SectionHeading, CTABand, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ||
  'https://proreadyengineer-training-api-jd9a.onrender.com';

/* ---------------------------------------------------------------------------
   Catalog comes from GET /api/products/software (the admin-managed registry),
   so shipping a new tool is an admin action, not a deploy. The hardcoded
   Pro3DWorks entry below is the fallback — it is what the prerendered HTML
   carries (useEffect never runs at build time) and what visitors see if the
   API is down, so the SEO copy for the flagship never depends on the API.
--------------------------------------------------------------------------- */
type SoftwareProduct = {
  slug: string;
  name: string;
  blurb: string;
  latest_version: string;
  download_count: number | null;
};

const PRO3DWORKS_FALLBACK: SoftwareProduct = {
  slug: 'pro3dworks',
  name: 'Pro3DWorks',
  blurb:
    'Open any CAD model. Free. Straight in your browser. Pro3DWorks is a complete viewer and inspection suite in a single HTML file — drop in a STEP, Parasolid or STL and you are measuring, sectioning and rendering in seconds.',
  latest_version: '2.53.2',
  download_count: null,
};

const features: { icon: React.ReactElement; title: string; text: string }[] = [
  {
    icon: <Boxes aria-hidden="true" className="w-5 h-5" />,
    title: 'Opens the formats that matter',
    text: 'STEP, IGES, STL, Parasolid (.x_t), 3MF, GLB, OBJ and more — including large assemblies, with an instant reopen cache.',
  },
  {
    icon: <Ruler aria-hidden="true" className="w-5 h-5" />,
    title: 'Real inspection tools',
    text: 'Measure vertices, edges and faces; section views; exploded views; mass properties; interference checks; model scaling.',
  },
  {
    icon: <Camera aria-hidden="true" className="w-5 h-5" />,
    title: 'Photoreal rendering',
    text: 'Ray-traced studio images and 4K exports — presentation-grade output straight from a browser tab.',
  },
  {
    icon: <Sparkles aria-hidden="true" className="w-5 h-5" />,
    title: 'AI Engineer built in',
    text: 'Identify components, color by function, generate a BOM with order-of-magnitude cost estimates (exported as a formatted Excel workbook), review the design, or chat with your model. Works with any OpenAI-compatible endpoint — or fully local and private with LM Studio.',
  },
  {
    icon: <CircleDollarSign aria-hidden="true" className="w-5 h-5" />,
    title: 'Estimates your cost savings — AI vs. manual labor',
    text: 'Every AI run is metered in real dollars, and the built-in cost & savings log estimates what the same work would cost an engineer doing it by hand, at your own labor rate. Each model session becomes a line item — AI cost, manual estimate, and money saved — with a running total.',
  },
  {
    icon: <ShieldCheck aria-hidden="true" className="w-5 h-5" />,
    title: 'Private by design',
    text: 'One HTML file that runs entirely on your machine. No install, no account, no upload — your models never leave your computer.',
  },
];

/** "2.53.2" or "v2.53.2" -> "v2.53.2"; empty stays empty. */
const versionLabel = (v: string): string => (v ? `v${v.replace(/^v/i, '')}` : '');

export default function Products() {
  usePageMeta(
    'Products — Free Engineering Software',
    'Free engineering software by ProReadyEngineer LLC. Pro3DWorks: browser CAD viewer — measure, section, photoreal render, AI-assisted BOM, and estimated cost savings of AI vs manual work.',
  );

  const [products, setProducts] = useState<SoftwareProduct[]>([PRO3DWORKS_FALLBACK]);
  useEffect(() => {
    let cancelled = false;
    // The API sleeps on Render's free tier and takes 30-60 s to wake. A
    // single fetch dies against that cold start (mobile visitors saw no
    // counter); retrying with backoff lets attempt 1 wake the server and a
    // later attempt fill the catalog + counters a few seconds after.
    const attempt = (retriesLeft: number, delayMs: number) => {
      fetch(`${API_BASE}/api/products/software`)
        .then((r) => (r.ok ? r.json() : null))
        .then((list) => {
          if (cancelled) return;
          if (Array.isArray(list) && list.length > 0) setProducts(list as SoftwareProduct[]);
          else if (retriesLeft > 0) setTimeout(() => attempt(retriesLeft - 1, delayMs * 2.5), delayMs);
        })
        .catch(() => {
          if (!cancelled && retriesLeft > 0) setTimeout(() => attempt(retriesLeft - 1, delayMs * 2.5), delayMs);
        });
    };
    attempt(3, 8000);
    return () => { cancelled = true; };
  }, []);

  // The flagship keeps its hand-written marketing card; only its version and
  // download counter go live. Everything else renders as a catalog card.
  const pro3d = products.find((p) => p.slug === 'pro3dworks');
  const others = products.filter((p) => p.slug !== 'pro3dworks');
  const downloads = pro3d?.download_count ?? null;

  return (
    <>
      <PageHero
        eyebrow="Products"
        title={<>Free engineering software, <span className="text-gradient">built by engineers</span></>}
        subtitle="Tools we built for our own consulting work, released free for the engineering community. No accounts, no trials — download and work."
      />

      {/* ---------- Pro3DWorks ---------- */}
      {pro3d && (
        <section className="section-pad pt-4">
          <div className="container-site">
            <Reveal className="card relative overflow-hidden px-6 py-10 md:px-12 md:py-12">
              <div
                className="absolute -top-24 right-0 w-[45%] h-56 bg-cyan-500/10 blur-[110px] rounded-full pointer-events-none"
                aria-hidden="true"
              />
              <div className="grid lg:grid-cols-2 gap-10 items-start">
                <div>
                  <span className="eyebrow mb-4">Browser CAD viewer &amp; AI inspector</span>
                  <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">
                    Pro3D<span className="text-cyan-400">Works</span>
                  </h2>
                  <p className="text-slate-300 leading-relaxed mb-6">
                    Open any CAD model. Free. Straight in your browser. Pro3DWorks is a complete
                    viewer and inspection suite in a single HTML file — drop in a STEP, Parasolid
                    or STL and you are measuring, sectioning and rendering in seconds.
                  </p>
                  <div className="flex flex-col sm:flex-row sm:items-center gap-4 mb-3">
                    <a
                      href="/download/pro3dworks"
                      className="btn-primary"
                      download="Pro3DWorks.html"
                    >
                      <Download className="w-4 h-4" aria-hidden="true" />
                      Download Pro3DWorks — free
                    </a>
                    <a
                      href="https://buy.stripe.com/dRmdRb54gg8RgBmbkCcjS00"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-ghost"
                    >
                      <Heart className="w-4 h-4 text-amber-400" aria-hidden="true" />
                      Support development
                    </a>
                  </div>
                  <p className="text-sm text-slate-400">
                    {versionLabel(pro3d.latest_version) || 'v2.53.2'} · single HTML file · ~9&nbsp;MB · Windows / Mac / Linux · works offline
                    {downloads !== null && downloads > 0 && (
                      <> · <span className="text-cyan-300">{downloads.toLocaleString()} download{downloads === 1 ? '' : 's'}</span></>
                    )}
                  </p>
                  <div className="mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                    <p className="text-sm text-slate-300 font-semibold mb-2">Getting started — 30 seconds</p>
                    <ol className="text-sm text-slate-400 space-y-1 list-decimal list-inside">
                      <li>Download and save <span className="text-slate-300">Pro3DWorks.html</span> anywhere.</li>
                      <li>Double-click it — it opens in your browser like a normal app.</li>
                      <li>Drag a CAD file in, or press <span className="text-slate-300">Load demo assembly</span>.</li>
                    </ol>
                  </div>
                </div>
                <div className="space-y-4">
                  {features.map((f) => (
                    <div key={f.title} className="flex gap-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
                      <div className="text-cyan-400 mt-0.5 shrink-0">{f.icon}</div>
                      <div>
                        <p className="font-semibold text-slate-100 mb-1 flex items-center gap-2">
                          {f.title}
                          <CheckCircle2 className="w-4 h-4 text-emerald-400/80" aria-hidden="true" />
                        </p>
                        <p className="text-sm text-slate-400 leading-relaxed">{f.text}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Reveal>
          </div>
        </section>
      )}

      {/* ---------- Other registry products ---------- */}
      {others.length > 0 && (
        <section className={pro3d ? 'pb-20' : 'section-pad pt-4'}>
          <div className="container-site">
            <div className={`grid grid-cols-1 gap-6 ${others.length > 1 ? 'md:grid-cols-2' : 'max-w-2xl mx-auto'}`}>
              {others.map((p, i) => (
                <Reveal key={p.slug} delay={(i % 2) * 0.07}>
                  <div className="card card-hover p-7 h-full flex flex-col">
                    <h3 className="text-xl font-bold mb-3">{p.name}</h3>
                    {p.blurb && (
                      <p className="text-slate-300 text-sm leading-relaxed mb-6 flex-grow whitespace-pre-line">
                        {p.blurb}
                      </p>
                    )}
                    <p className="text-sm text-slate-400 mb-5">
                      {versionLabel(p.latest_version)}
                      {typeof p.download_count === 'number' && p.download_count > 0 && (
                        <>
                          {p.latest_version ? ' · ' : ''}
                          <span className="text-cyan-300">
                            {p.download_count.toLocaleString()} download{p.download_count === 1 ? '' : 's'}
                          </span>
                        </>
                      )}
                    </p>
                    <a href={`/download/${p.slug}`} className="btn-primary mt-auto justify-center" download>
                      <Download className="w-4 h-4" aria-hidden="true" />
                      Download {p.name} — free
                    </a>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* ---------- More coming ---------- */}
      <section className="section-pad pt-0">
        <div className="container-site">
          <SectionHeading
            eyebrow="On the bench"
            title="More tools on the way"
            subtitle="The Combustion Engineering Toolkit and our 1-D compressible flow network simulator are next in line to join this page."
          />
        </div>
      </section>

      <CTABand
        title="Need the engineers behind the tools?"
        subtitle="The same team that builds this software designs, tests and troubleshoots gas turbine combustion and thermal-fluid systems for clients worldwide."
      />
    </>
  );
}
