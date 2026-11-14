import React, { useEffect, useState } from 'react';
import {
  Download, ShieldCheck, Sparkles, Boxes, Camera, Ruler, Heart, CircleDollarSign, ClipboardCheck,
  PlayCircle, Factory, FileText, Check, ChevronDown,
} from 'lucide-react';
import highlightsJson from '../data/pro3dworks-highlights.json';
import Img from '../components/Img';
import { Reveal, SectionHeading, CTABand, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ||
  'https://api.proreadyengineer.com';

const DOWNLOAD_URL = '/download/pro3dworks';
const SUPPORT_URL = 'https://buy.stripe.com/dRmdRb54gg8RgBmbkCcjS00';

/* ---------- "What's new": fed by the Pro3DWorks release job ----------
   Each release, a job in the Pro3DWorks repository copies its
   release-highlights.json over src/data/pro3dworks-highlights.json. This
   reads that file in two shapes:

     current   highlights: [{ title, text }, ...]  3 to 6 short cards, plus an
               optional `summary` and `notes` (technical statements)
     earlier   highlights: ["a long sentence", ...]

   Cards are shown as cards. Plain sentences and `notes` are listed under a
   closed "Technical release notes" heading, so a release written the old way
   can never again appear as one long paragraph on the page. */
type ReleaseCard = { title: string; text: string };
type Release = { version: string; name: string; summary: string; cards: ReleaseCard[]; notes: string[] };

function readRelease(raw: unknown): Release | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  if (typeof r.version !== 'string' || !r.version.trim()) return null;
  const text = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
  const cards: ReleaseCard[] = [];
  const notes: string[] = [];
  for (const item of Array.isArray(r.highlights) ? r.highlights : []) {
    if (typeof item === 'string') {
      if (item.trim()) notes.push(item.trim());
    } else if (item && typeof item === 'object') {
      const card = item as Record<string, unknown>;
      if (text(card.title) && text(card.text)) cards.push({ title: text(card.title), text: text(card.text) });
    }
  }
  for (const note of Array.isArray(r.notes) ? r.notes : []) {
    if (text(note)) notes.push(text(note));
  }
  if (cards.length === 0 && notes.length === 0) return null;
  return { version: r.version.trim(), name: text(r.name), summary: text(r.summary), cards: cards.slice(0, 6), notes };
}

const release = readRelease(highlightsJson);

/* ---------- What the product does ----------
   Every statement below is traced to the Pro3DWorks release documents
   (docs/RELEASE_*.md and README.md in the product repository) and to the text
   of the shipped Pro3DWorks.html. Where a tool screens rather than certifies,
   or needs something that is not in the download, the copy says so. */
type Capability = {
  icon: React.ReactElement;
  title: string;
  lead: string;
  points: string[];
  note?: string;
};

const capabilities: Capability[] = [
  {
    icon: <Boxes aria-hidden="true" className="w-5 h-5" />,
    title: 'Opens STEP, IGES and 50+ more',
    lead: 'True faces, edges and vertices from STEP, IGES and BREP, a visual model from mesh, text Parasolid and SolidWorks files, and a label that tells you which one you are looking at.',
    points: [
      'STEP, IGES and BREP through a built-in CAD kernel, with true faces, edges and vertices to measure from',
      'More than 50 mesh and scene file types: STL, OBJ, 3MF, GLB/glTF, PLY, FBX, DAE, USD and others',
      'Parasolid text (.x_t) assemblies as a visual model that shows its outline first, then sharpens as you look',
      'SolidWorks .sldprt and .sldasm display previews (not for older files in the legacy container format), and structure inspection for Siemens NX .prt and JT 9',
      'Large STEP assemblies import on several processor cores at once and reopen from a local cache',
    ],
  },
  {
    icon: <Ruler aria-hidden="true" className="w-5 h-5" />,
    title: 'Measure and inspect',
    lead: 'The questions you ask of a model, answered on the geometry itself.',
    points: [
      'Pick vertices, edges and faces: distances with their X, Y and Z components, radii, diameters, angles, arc lengths and areas',
      'Section views with capped cuts and a plane you drag through the model',
      'Mass properties (volume, mass by material, centre of mass, principal moments) and an interference check',
      'Exploded views, plus an automatic disassembly sequence you can play back or export as CSV, JSON or video',
      'Model health, geometry quality and standard-hardware checks: click a finding to select the parts it concerns',
      'Units from millimetres to feet and inches, including fractions down to 1/64',
    ],
    note: 'Measuring from true faces, edges and vertices needs a STEP, IGES or BREP file. Text Parasolid files and SolidWorks previews open for viewing only.',
  },
  {
    icon: <ClipboardCheck aria-hidden="true" className="w-5 h-5" />,
    title: 'Run the whole design review',
    lead: 'Mark up the model the way a review meeting does, then hand over one file.',
    points: [
      'Named views that bring back the camera, visibility, section, explode and display style',
      'Issue pins with owner, severity and status; 3D notes anchored to the part; arrows and rectangles drawn on a saved view',
      'Measurement callouts you can drag to where they read best',
      'Compare two revisions into a change map (moved, modified, added, removed) and find duplicate or near-identical parts',
      'A self-contained HTML report you can print to PDF, and inspection tables as CSV or Markdown',
      'Save the model and your review workspace as one .p3dproject file and reopen it later without the original CAD',
    ],
  },
  {
    icon: <Factory aria-hidden="true" className="w-5 h-5" />,
    title: 'Check it before you cut, print or mould',
    lead: 'Find the problems while they are still cheap to fix.',
    points: [
      'Mesh repair on a copy, never the original: seam cleaning, normals, small-hole filling and decimation, with a deviation map and undo',
      'FDM 3D-printing audit against the printer profile you enter: build volume, bed contact, overhangs and thin walls, compared across six build orientations',
      'CNC readiness against your stock, machine travel and cutter: reach and clearance across six setups',
      'Draft-angle analysis against a pull direction, for moulded, cast and forged parts',
    ],
    note: 'These are screening tools. They flag what needs attention before your slicer or CAM, and replace neither.',
  },
  {
    icon: <FileText aria-hidden="true" className="w-5 h-5" />,
    title: 'Drawings, GD&T and tolerance stacks',
    lead: 'From 3D model to a drawing sheet, a PMI audit and a tolerance study without leaving the tab.',
    points: [
      'Four-view drawing sheets (front, top, right, isometric) on A4, A3 or A2, in ASME third-angle or ISO first-angle, with hidden lines, overall dimensions and a title block; export SVG or HTML, or print to PDF',
      'Reads the PMI a designer wrote into a STEP AP242 file: dimensions, geometric tolerances, datums and graphical annotations, with a CSV audit',
      'One-dimensional tolerance stack-ups solved three ways (worst case, RSS and Monte Carlo), with the contributors ranked',
    ],
  },
  {
    icon: <Sparkles aria-hidden="true" className="w-5 h-5" />,
    title: 'AI Engineer, with you in command',
    lead: 'Connect the AI model of your choice and put it to work on the assembly. In chat and the command palette it proposes and you approve.',
    points: [
      'Identifies and colours components, orients the model, suggests part names and reviews the design against measured data',
      'Builds a bill of materials with budgetary cost estimates and exports it as a formatted Excel workbook',
      'Chat with the assembly: proposed actions wait for your approval before they run',
      'Works with any OpenAI-compatible endpoint that serves a vision-capable model, or fully local and private with LM Studio',
      'For the engineering analyses the AI only chooses which approved tool to run; the numbers come from deterministic local code',
    ],
    note: 'Needs your own AI endpoint or a local model, as do the AI cost log and the four truck lessons. Everything else on this page works without one.',
  },
  {
    icon: <CircleDollarSign aria-hidden="true" className="w-5 h-5" />,
    title: 'See what the AI cost, and what it saved',
    lead: 'A running account, in dollars, of every AI request.',
    points: [
      'Every request is metered in tokens and priced at the rate you set, pre-filled from a public price list; local LM Studio runs count as $0',
      'A built-in log sets that spend against an estimate of the same work done by hand, at your own labour rate',
      'One line per model session, with a running total',
    ],
  },
  {
    icon: <Camera aria-hidden="true" className="w-5 h-5" />,
    title: 'Photoreal rendering',
    lead: 'Presentation images from the same browser tab.',
    points: [
      'Path tracing on your own GPU: real reflections, global illumination, soft shadows and depth of field',
      'Six studio presets, from Neutral engineering to Polished product, that set backdrop, floor and tone without changing your part materials',
      'Save the path-traced image as a PNG at window size or twice that; a separate 4K PNG export captures the realistic display style',
    ],
  },
  {
    icon: <PlayCircle aria-hidden="true" className="w-5 h-5" />,
    title: 'Learn it by watching it work',
    lead: 'Eight narrated lessons, 83 steps, built into the app. They are not videos: an animated cursor drives the real interface, runs the real functions and leaves the finished work live for you to explore.',
    points: [
      'Four benchmark labs you can start straight away: revision comparison; geometry quality, repair and 3D printing; CNC readiness; drawings, PMI and tolerance stacks',
      'A four-part project on a complete 189-part truck assembly, led by the AI Engineer (so it needs your AI connection)',
      'Pause, step back and forward, or run from 0.75× to 2× speed',
    ],
  },
];

const stats: { value: string; label: string }[] = [
  { value: '1', label: 'HTML file. Nothing to install' },
  { value: '50+', label: 'file types, three read with true faces, edges and vertices' },
  { value: '8', label: 'narrated lessons inside the app, 4 of them with no AI needed' },
  { value: '0', label: 'accounts, installers or uploads needed' },
];

const faqs: { q: string; a: React.ReactNode }[] = [
  {
    q: 'Is it really free?',
    a: 'Yes. Pro3DWorks is free of charge for personal and commercial use, and you may pass the unmodified file on to colleagues. There is no account and no trial period. If it earns its place in your workflow, the Support development button is there. It is provided as is, without warranty, so verify results independently before an engineering, manufacturing or commercial decision rests on them.',
  },
  {
    q: 'Do my models leave my computer?',
    a: 'Your CAD files never do. The geometry is read and processed on your machine, and ProReadyEngineer never receives your models or file names. One thing is of your own choosing: if you connect the AI Engineer to a cloud endpoint, the screenshots and part data needed for the job you run go to that endpoint, never the source CAD file. Use LM Studio and even that stays on your computer. STEP, IGES, BREP and text Parasolid models you open are cached in your own browser so they reopen quickly; File, then Cache manager, in the app deletes those caches.',
  },
  {
    q: 'What do I need to run it?',
    a: 'A current desktop browser on Windows, Mac or Linux. Release testing is done in Chrome, so use Chrome if you can; the narrated lessons use the natural voices in Chrome or Edge. Photoreal rendering uses your graphics card. Pro3DWorks is a desktop tool: its layout needs a window at least 930 pixels wide.',
  },
  {
    q: 'How large a model can it open?',
    a: 'The truck in the built-in lessons is a 40.8 MB STEP assembly with 189 parts and 3.5 million triangles; in our own tests it opened in about 13 seconds on a 32-thread workstation and a little over two minutes on a 2-core test machine, and a model you have opened before reopens from a local cache. A single STEP file is practical up to roughly 250 to 450 MB, depending on what is in it, and needs about four to eight times its size in memory while it is read.',
  },
  {
    q: 'Does it open SolidWorks and NX files?',
    a: 'It shows the display preview saved inside a SolidWorks part or assembly, and the internal structure of Siemens NX and JT 9 files. The preview is not available for older SolidWorks files in the legacy container format, and an assembly needs its part files opened together with it. For true faces, edges and vertices you can measure from, export STEP from your CAD system: Pro3DWorks reads it with a real CAD kernel. Decoding native SolidWorks and NX geometry needs a separate Windows helper and a separately licensed converter; neither is included in, or available with, this download.',
  },
  {
    q: 'Can I edit or convert a model?',
    a: 'Pro3DWorks is a viewer, inspector and review tool, not a CAD authoring system: it does not edit features. You can scale a model, repair a mesh on a copy, and export what you see as GLB or STL, along with images, drawings, reports and tables. STEP export is not included.',
  },
];

const networkTouches: { name: string; detail: string }[] = [
  { name: 'Update check', detail: 'At launch the app asks proreadyengineer.com once whether a newer free version exists. The request carries only the app name and version; the site logs it with an approximate location (country, region, city) and does not store your network address. On by default, with a switch to turn it off.' },
  { name: 'Anonymous usage ping', detail: 'Off unless you switch it on. If you do: app version, minutes open and feature counts, kept with an approximate city and region. No model data, no file names, no account, no installation ID.' },
  { name: 'Links you click', detail: 'Buttons that open this site carry the app version in the address. Nothing is sent in the background.' },
  { name: 'AI price list', detail: 'While no prices are entered for a cloud endpoint, running an AI feature or changing the model name makes the app download the public list of AI model prices from OpenRouter; the price lookup button does the same. With LM Studio selected it is never requested.' },
];

/* A real screenshot of the app in a plain window frame. */
const AppWindow = ({ src, alt, caption, priority, sizes }: {
  src: string; alt: string; caption?: string; priority?: boolean; sizes: string;
}) => (
  <figure>
    <div className="rounded-xl border border-slate-700/70 bg-slate-900 overflow-hidden shadow-glow-cyan">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-slate-800 bg-slate-950/80" aria-hidden="true">
        <span className="w-2.5 h-2.5 rounded-full bg-slate-700" />
        <span className="w-2.5 h-2.5 rounded-full bg-slate-700" />
        <span className="w-2.5 h-2.5 rounded-full bg-slate-700" />
        <span className="ml-3 text-[11px] font-mono text-slate-400 truncate">Pro3DWorks.html</span>
      </div>
      <a href={src} target="_blank" rel="noopener" title="Open the full-size screen">
        <Img src={src} alt={alt} sizes={sizes} priority={priority} className="block w-full h-auto" />
      </a>
    </div>
    {caption && <figcaption className="mt-3 text-sm text-slate-400 leading-relaxed">{caption}</figcaption>}
  </figure>
);

const DownloadButton = ({ label = 'Download Pro3DWorks, free' }: { label?: string }) => (
  <a href={DOWNLOAD_URL} className="btn-primary" download="Pro3DWorks.html">
    <Download className="w-4 h-4" aria-hidden="true" />
    {label}
  </a>
);

export default function Products() {
  usePageMeta(
    'Pro3DWorks: Free Browser CAD Viewer and Inspection Suite',
    'Free CAD viewer, inspection and design-review suite in one HTML file. Open STEP, IGES, STL and text Parasolid; measure, section, check parts for 3D printing and CNC, make drawings, read GD&T and render, all on your own computer.',
    {
      jsonLd: {
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Pro3DWorks',
        applicationCategory: 'DesignApplication',
        operatingSystem: 'Windows, macOS, Linux',
        ...(release ? { softwareVersion: release.version } : {}),
        description:
          'Free browser-based CAD viewer, inspection and design-review suite in a single HTML file, with measurement, sectioning, revision comparison, manufacturing checks, drawings, GD&T, tolerance stack-ups, photoreal rendering and an optional AI Engineer.',
        downloadUrl: 'https://proreadyengineer.com/download/pro3dworks',
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
        publisher: { '@type': 'Organization', name: 'ProReadyEngineer LLC', url: 'https://proreadyengineer.com' },
      },
    },
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

      {/* ---------- Pro3DWorks: the product ---------- */}
      <section className="section-pad pt-4 pb-10 lg:pb-14">
        <div className="container-site">
          <Reveal className="card relative overflow-hidden px-6 py-10 md:px-12 md:py-14">
            <div
              className="absolute -top-24 right-0 w-[45%] h-56 bg-cyan-500/10 blur-[110px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <div className="grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] gap-10 lg:gap-14 items-center">
              <div>
                <span className="eyebrow mb-4">Browser CAD viewer &amp; inspection suite</span>
                <h2 className="text-4xl md:text-5xl font-bold tracking-tight mt-3 mb-4">
                  Pro3D<span className="text-cyan-400">Works</span>
                </h2>
                <p className="text-xl md:text-2xl font-semibold text-slate-100 leading-snug mb-4">
                  Open the model. Measure it, review it, check it for the shop, render it.{' '}
                  <span className="text-gradient">Free, in one file.</span>
                </p>
                <p className="text-slate-300 leading-relaxed mb-7">
                  Pro3DWorks is a CAD viewer, inspection and design-review suite that lives in a
                  single HTML file. Drop in a STEP, IGES or STL file and start measuring,
                  sectioning and rendering. No install, no account, no upload: the geometry and
                  every engineering calculation stay on your own machine.
                </p>
                <div className="flex flex-col sm:flex-row sm:items-center gap-4 mb-4">
                  <DownloadButton />
                  <a href={SUPPORT_URL} target="_blank" rel="noopener noreferrer" className="btn-ghost">
                    <Heart className="w-4 h-4 text-amber-400" aria-hidden="true" />
                    Support development
                  </a>
                </div>
                {/* The Pro3DWorks release job rewrites the version and size on the
                    next line with a text search. Keep its wording and its place in
                    this file exactly as they are, or the next release cannot publish. */}
                <p className="text-sm text-slate-400">
                  v2.69.1 · single HTML file · ~23&nbsp;MB · Windows / Mac / Linux · works offline
                  {downloads !== null && downloads > 0 && (
                    <> · <span className="text-cyan-300">{downloads.toLocaleString()} download{downloads === 1 ? '' : 's'}</span></>
                  )}
                </p>
                <ol className="mt-7 grid sm:grid-cols-3 gap-3 text-sm">
                  {[
                    ['Download', <>Save <span className="text-slate-200">Pro3DWorks.html</span> anywhere.</>],
                    ['Open', <>Double-click it. It opens in your browser like an app.</>],
                    ['Work', <>Drag a CAD file in, or press <span className="text-slate-200">Load demo assembly</span>.</>],
                  ].map(([step, body], i) => (
                    <li key={i} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                      <span className="block font-mono text-xs uppercase tracking-widest text-cyan-400 mb-1">
                        {i + 1}. {step}
                      </span>
                      <span className="text-slate-400 leading-relaxed">{body}</span>
                    </li>
                  ))}
                </ol>
              </div>
              <AppWindow
                src="/Pro3DWorks_PMI_Review.png"
                alt="Pro3DWorks in a browser window showing a machined benchmark part with its dimension and tolerance annotations drawn on the 3D model, and the PMI and GD&T review panel listing 8 dimensions, 6 GD&T controls and 3 datums"
                caption="A NIST benchmark part open in a browser tab. The dimensions, geometric tolerances and datums its designer wrote into the STEP AP242 file are read, listed and shown on the model."
                sizes="(min-width: 1024px) 620px, 100vw"
                priority
              />
            </div>
          </Reveal>

          {/* ---------- At a glance ---------- */}
          <Reveal className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-4">
            {stats.map((s) => (
              <div key={s.label} className="card px-5 py-6 text-center">
                <div className="font-display text-4xl md:text-5xl font-bold text-gradient tabular-nums">{s.value}</div>
                <div className="mt-2 text-sm text-slate-300 leading-snug">{s.label}</div>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      {/* ---------- What's new (fed by each release) ---------- */}
      {release && (
        <section className="pb-10 lg:pb-14" id="whats-new">
          <div className="container-site">
            <Reveal className="relative overflow-hidden rounded-2xl border border-cyan-500/25 bg-cyan-500/[0.04] px-6 py-9 md:px-12 md:py-11">
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <span className="eyebrow">What&rsquo;s new</span>
                <span className="font-mono text-xs uppercase tracking-widest text-slate-400">Version {release.version}</span>
              </div>
              {release.name && (
                <h2 className="text-2xl md:text-3xl font-bold tracking-tight max-w-4xl mb-3">{release.name}</h2>
              )}
              {release.summary && <p className="text-slate-300 leading-relaxed max-w-3xl">{release.summary}</p>}
              {release.cards.length > 0 && (
                <ul className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {release.cards.map((c) => (
                    <li key={c.title} className="rounded-xl border border-slate-800 bg-slate-950/60 p-5">
                      <p className="font-semibold text-slate-100 mb-2">{c.title}</p>
                      <p className="text-sm text-slate-400 leading-relaxed">{c.text}</p>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-8 flex flex-col sm:flex-row sm:items-center gap-4">
                <DownloadButton label={`Get version ${release.version}`} />
                <span className="text-sm text-slate-400">
                  Already using Pro3DWorks? Download the new file and open it in place of the old one.
                </span>
              </div>
              {release.notes.length > 0 && (
                <details className="group mt-8 border-t border-slate-800 pt-5">
                  <summary className="flex items-center gap-2 cursor-pointer list-none text-sm font-medium text-cyan-400 hover:text-cyan-300 [&::-webkit-details-marker]:hidden">
                    <ChevronDown className="w-4 h-4 transition-transform group-open:rotate-180" aria-hidden="true" />
                    Technical release notes
                  </summary>
                  <ul className="mt-4 space-y-2 text-sm text-slate-400 leading-relaxed list-disc pl-5 max-w-4xl">
                    {release.notes.map((n) => <li key={n}>{n}</li>)}
                  </ul>
                </details>
              )}
            </Reveal>
          </div>
        </section>
      )}

      {/* ---------- What it does ---------- */}
      <section className="section-pad pt-10 lg:pt-14">
        <div className="container-site">
          <SectionHeading
            eyebrow="What it does"
            title={<>An engineering review bench <span className="text-gradient">in one file</span></>}
            subtitle="Pro3DWorks goes on from viewing to inspection, design review, manufacturing checks and documentation."
          />
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-6">
            {capabilities.map((c) => (
              <Reveal key={c.title} className="card card-hover p-6 flex flex-col">
                <div className="flex items-center gap-3 mb-3">
                  <span className="shrink-0 inline-flex items-center justify-center w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
                    {c.icon}
                  </span>
                  <h3 className="text-lg font-semibold text-slate-100 leading-snug">{c.title}</h3>
                </div>
                <p className="text-sm text-slate-300 leading-relaxed mb-4">{c.lead}</p>
                <ul className="space-y-2.5 text-sm text-slate-400 leading-relaxed">
                  {c.points.map((p) => (
                    <li key={p} className="flex gap-2.5">
                      <Check className="w-4 h-4 mt-0.5 shrink-0 text-emerald-400/80" aria-hidden="true" />
                      <span>{p}</span>
                    </li>
                  ))}
                </ul>
                {c.note && (
                  <p className="mt-auto pt-5 text-xs text-slate-400 leading-relaxed">
                    <span className="block border-t border-slate-800 pt-4">{c.note}</span>
                  </p>
                )}
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- Seen working ---------- */}
      <section className="section-pad pt-0">
        <div className="container-site">
          <SectionHeading
            eyebrow="Seen working"
            title="Straight from the app"
            subtitle="Real screens of Pro3DWorks, on the public benchmark parts that ship inside it."
          />
          <div className="grid lg:grid-cols-2 gap-8">
            <Reveal>
              <AppWindow
                src="/Pro3DWorks_Printability_Audit.png"
                alt="Pro3DWorks 3D printability audit on a test part: a printer profile with bed size, layer height and nozzle, and a table comparing six build directions by overhang, bed contact and height"
                caption="The 3D-printing audit: enter your printer profile, and six build directions are compared by blockers, overhang, bed contact and height."
                sizes="(min-width: 1024px) 600px, 100vw"
              />
            </Reveal>
            <Reveal delay={0.1}>
              <AppWindow
                src="/Pro3DWorks_Section_View.png"
                alt="Pro3DWorks section view panel cutting a machined benchmark part in half along a plane, with the cut face capped"
                caption="A section view: choose a plane, drag it through the part, and the cut face is capped."
                sizes="(min-width: 1024px) 600px, 100vw"
              />
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- Private by design ---------- */}
      <section className="section-pad pt-0">
        <div className="container-site">
          <Reveal className="card relative overflow-hidden px-6 py-10 md:px-12 md:py-12">
            <div className="grid lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-10 items-start">
              <div>
                <span className="eyebrow mb-4">
                  <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" /> Private by design
                </span>
                <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">
                  Your CAD files stay on your computer
                </h2>
                <p className="text-slate-300 leading-relaxed mb-4">
                  Pro3DWorks is one HTML file that runs on your machine and works offline. Your
                  models and file names are never sent to ProReadyEngineer. The{' '}
                  <span className="text-slate-100">?</span> button in the app lists the Internet
                  requests it can make, and holds the on/off switches for the update check and the
                  usage ping.
                </p>
                <p className="text-sm text-slate-400 leading-relaxed">
                  If you run the AI Engineer, the screenshots and part data for that job go to the
                  AI endpoint you configured: your own cloud account, or LM Studio on your computer,
                  in which case nothing leaves your machine.
                </p>
              </div>
              <ul className="grid sm:grid-cols-2 gap-4">
                {networkTouches.map((n) => (
                  <li key={n.name} className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
                    <p className="font-semibold text-slate-100 mb-1.5">{n.name}</p>
                    <p className="text-sm text-slate-400 leading-relaxed">{n.detail}</p>
                  </li>
                ))}
              </ul>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------- Questions ---------- */}
      <section className="section-pad pt-0">
        <div className="container-site max-w-4xl">
          <SectionHeading eyebrow="Questions" title="Before you download" />
          <div className="space-y-3">
            {faqs.map((f) => (
              <details key={f.q} className="group card px-6 py-5">
                <summary className="flex items-center justify-between gap-4 cursor-pointer list-none font-semibold text-slate-100 [&::-webkit-details-marker]:hidden">
                  {f.q}
                  <ChevronDown className="w-5 h-5 shrink-0 text-cyan-400 transition-transform group-open:rotate-180" aria-hidden="true" />
                </summary>
                <p className="mt-4 text-slate-300 leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- Download ---------- */}
      <section className="section-pad pt-0">
        <div className="container-site">
          <Reveal className="card relative overflow-hidden text-center px-6 py-14 md:px-16">
            <div
              className="absolute -top-24 left-1/2 -translate-x-1/2 w-[60%] h-48 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none"
              aria-hidden="true"
            />
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">
              One file between you and <span className="text-gradient">your model</span>
            </h2>
            <p className="text-slate-300 max-w-2xl mx-auto mb-8">
              One download, no sign-up, nothing to install.
            </p>
            <div className="flex flex-col sm:flex-row justify-center items-center gap-4">
              <DownloadButton />
              <a href={SUPPORT_URL} target="_blank" rel="noopener noreferrer" className="btn-ghost">
                <Heart className="w-4 h-4 text-amber-400" aria-hidden="true" />
                Support development
              </a>
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
