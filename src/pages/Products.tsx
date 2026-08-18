import React, { useEffect, useState } from 'react';
import {
  Download, CheckCircle2, ShieldCheck, Sparkles, Boxes, Camera, Ruler, Heart, CircleDollarSign, ClipboardCheck, Wand2, FolderOpen, GitCompare,
} from 'lucide-react';
import highlights from '../data/pro3dworks-highlights.json';
import { Reveal, SectionHeading, CTABand, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ||
  'https://proreadyengineer-training-api-jd9a.onrender.com';

const features: { icon: React.ReactElement; title: string; text: string }[] = [
  {
    icon: <Boxes aria-hidden="true" className="w-5 h-5" />,
    title: 'Opens the formats that matter',
    text: 'STEP, IGES, STL, Parasolid (.x_t), 3MF, GLB, OBJ and more — including large assemblies, with an instant reopen cache.',
  },
  {
    icon: <FolderOpen aria-hidden="true" className="w-5 h-5" />,
    title: 'Save the whole review as a project',
    text: 'One .p3dproject file captures the model plus your entire workspace — names, classifications and materials, visibility, bookmarks, issues, redlines, captured measurements, camera and section state. Reopen it tomorrow and continue exactly where you stopped — without the original CAD file. Ctrl+S and done.',
  },
  {
    icon: <Ruler aria-hidden="true" className="w-5 h-5" />,
    title: 'Real inspection tools',
    text: 'Measure vertices, edges and faces; section views; mass properties; interference checks; model scaling. Exploded views now generate automatic, collision-screened disassembly sequences — play them back or export CSV, JSON and WebM. Plus a persistent Object Inspector, a deterministic model/import health report, and geometry-quality scans that catch sliver triangles, open boundaries and non-manifold edges.',
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
    icon: <ClipboardCheck aria-hidden="true" className="w-5 h-5" />,
    title: 'Design reviews that remember',
    text: 'Run a real design review inside the viewer: named view bookmarks, issue pins tied to the exact camera view, arrow and rectangle redlines with captured measurements. Export the whole review as CSV or a self-contained HTML/PDF package — every markup composited over a snapshot of the model.',
  },
  {
    icon: <GitCompare aria-hidden="true" className="w-5 h-5" />,
    title: 'Engineering change review — two revisions, one answer',
    text: 'Load revision A and revision B side by side and get a deterministic change map: modified, moved, added, removed, metadata-only and unchanged — a detected global shift is disclosed and removed before anything is classified as moved. The same geometry fingerprints power a duplicate and similar-part finder: exact repeats, opposite-handed, scaled and near-similar families, each selectable or isolated with size, area and volume evidence.',
  },
  {
    icon: <Wand2 aria-hidden="true" className="w-5 h-5" />,
    title: 'Engineering Review Copilot — commands you approve',
    text: 'Describe a viewer task in plain words — isolate these parts, section that view, save this review state. The safe command palette previews every proposed step with evidence, confidence and exact match counts; nothing runs until you approve it, and every action is audited and restorable. Explicit wording works fully offline — your configured AI can interpret broader phrasing, gated by the same strict validator. Plus a confidence-ranked, undoable BOM cleanup: material gaps are never guessed.',
  },
  {
    icon: <CircleDollarSign aria-hidden="true" className="w-5 h-5" />,
    title: 'Estimates your cost savings — AI vs. manual labor',
    text: 'Every AI run is metered in real dollars, and the built-in cost & savings log estimates what the same work would cost an engineer doing it by hand, at your own labor rate. Each model session becomes a line item — AI cost, manual estimate, and money saved — with a running total.',
  },
  {
    icon: <ShieldCheck aria-hidden="true" className="w-5 h-5" />,
    title: 'Private by design',
    text: 'One HTML file that runs entirely on your machine. No install, no account, no upload — your models never leave your computer. A ? button in the app lists every network touch this file can make — each with an off switch.',
  },
];

export default function Products() {
  usePageMeta(
    'Products — Free Engineering Software',
    'Free engineering software by ProReadyEngineer LLC. Pro3DWorks: browser CAD viewer — measure, section, photoreal render, AI-assisted BOM, and estimated cost savings of AI vs manual work.',
  );

  const [downloads, setDownloads] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    // The stats API sleeps on Render's free tier and takes 30-60 s to wake.
    // A single fetch dies against that cold start (mobile visitors saw no
    // counter); retrying with backoff lets attempt 1 wake the server and a
    // later attempt fill the counter a few seconds after.
    const attempt = (retriesLeft: number, delayMs: number) => {
      fetch(`${API_BASE}/api/downloads/stats?product=pro3dworks`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (cancelled) return;
          if (d && typeof d.total === 'number') setDownloads(d.total);
          else if (retriesLeft > 0) setTimeout(() => attempt(retriesLeft - 1, delayMs * 2.5), delayMs);
        })
        .catch(() => {
          if (!cancelled && retriesLeft > 0) setTimeout(() => attempt(retriesLeft - 1, delayMs * 2.5), delayMs);
        });
    };
    attempt(3, 8000);
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <PageHero
        eyebrow="Products"
        title={<>Free engineering software, <span className="text-gradient">built by engineers</span></>}
        subtitle="Tools we built for our own consulting work, released free for the engineering community. No accounts, no trials — download and work."
      />

      {/* ---------- Pro3DWorks ---------- */}
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
                  v2.56.0 · single HTML file · ~10&nbsp;MB · Windows / Mac / Linux · works offline
                  {downloads !== null && downloads > 0 && (
                    <> · <span className="text-cyan-300">{downloads.toLocaleString()} download{downloads === 1 ? '' : 's'}</span></>
                  )}
                </p>
                {highlights?.version && highlights.highlights?.length > 0 && (
                  <div className="mt-4 rounded-lg border border-cyan-500/25 bg-cyan-500/5 px-4 py-3 text-sm">
                    <span className="text-cyan-300 font-semibold">
                      New in v{highlights.version}
                      {highlights.name ? ` — ${highlights.name}` : ''}:
                    </span>{' '}
                    <span className="text-slate-300">{highlights.highlights.join(' · ')}</span>
                  </div>
                )}
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
