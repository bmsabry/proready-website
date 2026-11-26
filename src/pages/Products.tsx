import React from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Download,
  Layers,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { usePageMeta } from '../lib/meta';
import { PRODUCTS } from '../data/products';
import Img from '../components/Img';
import { Reveal } from '../components/ui';

export default function Products() {
  usePageMeta(
    'Engineering Software Products | Pro3DWorks v3',
    'Desktop engineering software built by ProReadyEngineer LLC. Explore Pro3DWorks v3 for Windows x64 — 3D CAD inspection, SolidWorks & NX native viewing, and Waterjet PDF-to-DXF/DWG conversion.',
    { image: 'https://proreadyengineer.com/Pro3DWorks_Hero_Assembly.png' },
  );

  return (
    <div className="bg-slate-950 text-slate-50 min-h-screen">
      {/* Hero Header */}
      <section className="relative pt-28 pb-16 lg:pt-36 lg:pb-20 overflow-hidden border-b border-slate-800/80">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(34,211,238,0.12),transparent_60%)]"
        />
        <div className="container-site relative">
          <Reveal className="max-w-3xl">
            <span className="eyebrow mb-5">
              <Cpu className="w-3.5 h-3.5" /> Engineering Software Catalog
            </span>
            <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-white mb-6">
              Focused desktop tools for{' '}
              <span className="text-gradient">engineers &amp; fabrication shops</span>
            </h1>
            <p className="text-lg text-slate-300 leading-relaxed max-w-2xl">
              Practical Windows desktop software born out of real gas turbine, test-cell, and CNC/waterjet hardware programs. Runs locally on your workstation—zero mandatory cloud file uploads.
            </p>
          </Reveal>
        </div>
      </section>

      {/* Product Catalog Grid */}
      <section className="section-pad">
        <div className="container-site space-y-10">
          {PRODUCTS.map((product) => (
            <Reveal
              key={product.slug}
              className="card overflow-hidden border-slate-800/90 bg-slate-900/70"
            >
              <div className="grid lg:grid-cols-12 gap-0">
                {/* Preview side */}
                <div className="lg:col-span-6 min-w-0 relative bg-slate-950/90 border-b lg:border-b-0 lg:border-r border-slate-800/80 p-4 sm:p-6 flex flex-col justify-start">
                  <div className="rounded-xl overflow-hidden border border-slate-700/70 shadow-2xl">
                    <Img
                      src={product.heroImage}
                      alt={product.heroAlt}
                      className="w-full h-auto block"
                      priority
                    />
                  </div>
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400 font-mono">
                    <span>v{product.version} · {product.platform}</span>
                    <span className="text-cyan-400 font-semibold">{product.badge}</span>
                  </div>
                </div>

                {/* Summary side */}
                <div className="lg:col-span-6 min-w-0 p-6 sm:p-8 lg:p-10 flex flex-col justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2.5 mb-4">
                      <span className="px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/25 text-cyan-300 text-xs font-mono">
                        {product.category}
                      </span>
                      <span className="px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-300 text-xs font-mono">
                        Founding Launch Pricing
                      </span>
                    </div>

                    <h2 className="font-display text-3xl sm:text-4xl font-bold text-white mb-2">
                      {product.name}{' '}
                      <span className="text-lg font-mono font-normal text-cyan-400">
                        v{product.version}
                      </span>
                    </h2>
                    <p className="text-base font-medium text-cyan-200/90 mb-4">
                      {product.tagline}
                    </p>
                    <p className="text-sm sm:text-base text-slate-300 leading-relaxed mb-6">
                      {product.summary}
                    </p>

                    <ul className="space-y-2.5 mb-8">
                      {product.highlights.map((bullet) => (
                        <li
                          key={bullet}
                          className="flex items-start gap-2.5 text-sm text-slate-200"
                        >
                          <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                          <span>{bullet}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <div className="rounded-xl bg-slate-950/70 border border-slate-800 px-4 py-3 mb-5 flex flex-wrap items-baseline justify-between gap-3">
                      <div>
                        <span className="text-xs uppercase tracking-wider text-slate-400 block">
                          Founding Launch Offer
                        </span>
                        <span className="text-xl font-bold text-white">
                          From ${product.startingMonthlyPrice}/mo
                        </span>{' '}
                        <span className="text-sm text-slate-300">
                          or ${product.startingYearlyPrice}/yr
                        </span>{' '}
                        <span className="text-xs text-slate-400 line-through">
                          ${product.regularMonthlyPrice}/mo
                        </span>
                      </div>
                      <span className="text-xs text-emerald-300 font-medium">
                        {product.trialDays}-day free Pro trial · Free basic 3D viewer included
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-3">
                      <Link to={product.route} className="btn-primary flex-1 sm:flex-none">
                        Explore {product.name} &amp; Pricing
                        <ArrowRight className="w-4 h-4" />
                      </Link>
                      <a
                        href={`/download/${product.downloadSlug}`}
                        className="btn-secondary flex-1 sm:flex-none"
                      >
                        <Download className="w-4 h-4 text-cyan-400" />
                        Download 15-Day Trial (.exe)
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </Reveal>
          ))}

          {/* Future Roadmap / Pipeline Strip */}
          <Reveal className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/30 p-8 sm:p-10">
            <div className="grid md:grid-cols-12 gap-6 items-center">
              <div className="md:col-span-8">
                <div className="inline-flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-slate-400 mb-2">
                  <Layers className="w-4 h-4 text-cyan-400" /> Expanding Product Suite
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-2">
                  More specialized engineering tools are in active development
                </h3>
                <p className="text-sm text-slate-300 leading-relaxed max-w-2xl">
                  This software hub houses every desktop tool published by ProReadyEngineer LLC. Future standalone utilities for thermal/combustion sizing, test-rig instrumentation diagnostics, and shop CAM prep will launch here as brief cards linking to dedicated documentation, screenshots, and licensing pages.
                </p>
              </div>
              <div className="md:col-span-4 flex flex-col sm:flex-row md:flex-col gap-3 md:items-end">
                <Link to="/contact" className="btn-secondary w-full sm:w-auto text-sm">
                  <Sparkles className="w-4 h-4 text-cyan-400" /> Request a Tool or Enterprise License
                </Link>
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Direct offline-first desktop licensing via Stripe</span>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
