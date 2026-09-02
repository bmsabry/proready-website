import React, { useEffect, useState } from 'react';
import {
  Download, CheckCircle2, ShieldCheck, Sparkles, Boxes, Camera, Ruler, Heart, CircleDollarSign, ClipboardCheck,
  PlayCircle, Factory, FileText,
} from 'lucide-react';
import highlights from '../data/pro3dworks-highlights.json';
import { Reveal, SectionHeading, CTABand, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ||
  'https://proreadyengineer-training-api-jd9a.onrender.com';

// Every claim below maps to a capability documented in the Pro3DWorks release
// guides (docs/RELEASE_*.md in the product repo) and shipped in the current
// build. Order is a reader's path, not a changelog: what it opens, how you
// learn it, what you can measure, review, manufacture and document, then the
// AI, the value and the privacy promise.
const features: { icon: React.ReactElement; title: string; text: string }[] = [
  {
    icon: <Boxes aria-hidden="true" className="w-5 h-5" />,
    title: 'Opens the formats that matter',
    text: 'STEP, IGES, STL, Parasolid (.x_t), 3MF, GLB, OBJ and more, including large assemblies, with an instant reopen cache.',
  },
  {
    icon: <PlayCircle aria-hidden="true" className="w-5 h-5" />,
    title: 'Learn it by watching it work',
    text: 'Eight narrated tutorials, 83 steps, built into the app. These are not videos: an animated cursor drives the real interface, runs the real functions and speaks along, then leaves the finished work live for you to poke at. It starts on a full truck assembly and moves through CAX-IF, Autodesk FDM, Zenodo CNC and NIST AP242 benchmark parts. Pause, replay, skip, or run at 0.75× to 2× speed.',
  },
  {
    icon: <Ruler aria-hidden="true" className="w-5 h-5" />,
    title: 'Real inspection tools',
    text: 'Measure vertices, edges and faces; section views; mass properties; interference checks; model scaling; exploded views with automatic, collision-screened disassembly sequences you can play back or export. A persistent Object Inspector, deterministic health and geometry-quality checks, and evidence-gated recognition of standard hardware. Click a finding to frame the affected parts.',
  },
  {
    icon: <ClipboardCheck aria-hidden="true" className="w-5 h-5" />,
    title: 'The whole design review, start to finish',
    text: 'Mark up the model like a real review: named view bookmarks, issue pins tied to the exact camera view, redlines with captured measurements. Compare two revisions into a deterministic change map (modified, moved, added, removed) and find duplicate or similar parts by geometric fingerprint. Export it as CSV or a self-contained HTML/PDF review package, and save everything as one .p3dproject file: reopen it tomorrow, without the original CAD, exactly where you stopped.',
  },
  {
    icon: <Factory aria-hidden="true" className="w-5 h-5" />,
    title: 'Manufacturing checks before you cut or print',
    text: 'Repair meshes non-destructively (sanitation, normals, bounded hole filling, decimation) with deviation evidence and full undo. Audit a part for 3D printing against a printer profile you declare: build envelope, contact area, overhangs, thin walls, and a six-orientation comparison. Screen it for three-axis machining against your stated stock, travel and cutter: clearance, reach and access evidence across six setups. All of it runs locally and sits upstream of your slicer or CAM: it flags what needs attention and does not pretend to be either.',
  },
  {
    icon: <FileText aria-hidden="true" className="w-5 h-5" />,
    title: 'Drawings, PMI and tolerance stacks',
    text: 'Generate a conventional four-view drawing sheet (A4/A3/A2, ASME third-angle or ISO first-angle, hidden lines, envelope dimensions, title block) and export it as SVG, printable HTML or PDF. Read the GD&T the CAD author actually wrote into a STEP AP242 file: semantic dimensions, geometric tolerances, datums and graphical PMI, with integrity checks and a CSV audit trail. Then build a signed 1-D tolerance loop and solve it exactly: worst case, RSS and Monte Carlo, with contributors ranked by how much each one costs you.',
  },
  {
    icon: <Sparkles aria-hidden="true" className="w-5 h-5" />,
    title: 'AI Engineer built in, and you stay in command',
    text: 'Identify components, color by function, generate a BOM with cost estimates (formatted Excel export), review the design, or chat with your model through any OpenAI-compatible endpoint, or fully local and private with LM Studio. It can also drive the deterministic tools above: BOM, viewer commands, machining comparison, drawing generation, tolerance actions. Every proposed step is previewed with evidence and match counts, runs only after you approve it, and stays audited and restorable. The AI chooses which allow-listed action to run; the geometry and the engineering maths stay deterministic, and nothing invents design intent that was not in your model.',
  },
  {
    icon: <CircleDollarSign aria-hidden="true" className="w-5 h-5" />,
    title: 'Estimates your cost savings: AI vs. manual labor',
    text: 'Every AI run is metered in real dollars, and the built-in cost & savings log estimates what the same work would cost an engineer doing it by hand, at your own labor rate. Each model session becomes a line item (AI cost, manual estimate, and money saved) with a running total.',
  },
  {
    icon: <Camera aria-hidden="true" className="w-5 h-5" />,
    title: 'Photoreal rendering',
    text: 'Ray-traced studio images and 4K exports: presentation-grade output straight from a browser tab.',
  },
  {
    icon: <ShieldCheck aria-hidden="true" className="w-5 h-5" />,
    title: 'Private by design',
    text: 'One HTML file that runs entirely on your machine. No install, no account, no upload, and your models never leave your computer. A ? button in the app lists every network touch this file can make, each with an off switch.',
  },
];

export default function Products() {
  usePageMeta(
    'Products: Free Engineering Software',
    'Free engineering software by ProReadyEngineer LLC. Pro3DWorks: browser CAD viewer and inspection suite: measure, section, design review, mesh repair, 3D-print and CNC checks, drawings, PMI/GD&T, tolerance stack-ups, photoreal rendering and a built-in AI Engineer.',
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
        subtitle="Tools we built for our own consulting work, released free for the engineering community. No accounts, no trials. Download and work."
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
                  viewer, inspection and review suite in a single HTML file. Drop in a STEP,
                  Parasolid or STL and you are measuring, sectioning and rendering in seconds,
                  then keep going: design review, manufacturing checks, drawings, GD&amp;T and
                  tolerance stacks. Every calculation runs on your machine.
                </p>
                <div className="flex flex-col sm:flex-row sm:items-center gap-4 mb-3">
                  <a
                    href="/download/pro3dworks"
                    className="btn-primary"
                    download="Pro3DWorks.html"
                  >
                    <Download className="w-4 h-4" aria-hidden="true" />
                    Download Pro3DWorks, free
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
                  v2.64.0 · single HTML file · ~23&nbsp;MB · Windows / Mac / Linux · works offline
                  {downloads !== null && downloads > 0 && (
                    <> · <span className="text-cyan-300">{downloads.toLocaleString()} download{downloads === 1 ? '' : 's'}</span></>
                  )}
                </p>
                {highlights?.version && highlights.highlights?.length > 0 && (
                  <div className="mt-4 rounded-lg border border-cyan-500/25 bg-cyan-500/5 px-4 py-3 text-sm">
                    <span className="text-cyan-300 font-semibold">
                      New in v{highlights.version}
                      {highlights.name ? `: ${highlights.name}` : ''}
                    </span>{' '}
                    <span className="text-slate-300">{highlights.highlights.join(' · ')}</span>
                  </div>
                )}
                <div className="mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-sm text-slate-300 font-semibold mb-2">Getting started in 30 seconds</p>
                  <ol className="text-sm text-slate-400 space-y-1 list-decimal list-inside">
                    <li>Download and save <span className="text-slate-300">Pro3DWorks.html</span> anywhere.</li>
                    <li>Double-click it and it opens in your browser like a normal app.</li>
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
