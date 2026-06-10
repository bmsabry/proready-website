import React from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

import { usePageMeta } from '../../lib/meta';
const OilFiltrationParticleRemoval = () => {
  usePageMeta('Oil Filtration for Sensitive Optics Cooling Air', 'A dual-branch, multi-stage filtration system with health monitoring delivered ultra-clean cooling air, long filter life, and maintenance without interrupting testing.');

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <Link to="/case-studies" className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 transition-colors mb-12 group">
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Case Studies
        </Link>

        <div className="anim-enter">
          <h1 className="text-3xl md:text-5xl font-bold mb-8 leading-tight">
            Oil Filtration and Particle Removal in Sensitive Optics Cooling Air
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/proready-case-study-oil-filtration-and-particle-removal-in-sensitive-optics-cooling-air.pdf"
              download="proready-case-study-oil-filtration-and-particle-removal-in-sensitive-optics-cooling-air.pdf"
              className="btn-primary rounded-full"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img loading="lazy" decoding="async" 
              src="/case-study-oil-filtration-and-particle-removal-in-sensitive-optics-cooling-air.jpg" 
              alt="Oil Filtration and Particle Removal" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Protecting Measurements, Hardware, and Emissions Integrity with a Multi‑Stage, Maintainable Filtration System</h2>
              
              <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
              <p><strong>Industry:</strong> Aerospace / Combustion Testing & Optical Diagnostics</p>
              <p><strong>Challenge:</strong> Contaminated cooling air was carrying oil and particles onto sensitive optics and into the combustor, risking hardware damage and biased emissions data.</p>
              <p><strong>Result:</strong> A dual‑branch, multi‑stage filtration system with health monitoring enabled ultra‑clean air delivery, long filter life, and on‑the‑fly maintenance without interrupting testing.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>
              <p>
                During an assessment of a client’s combustion test cell, we observed that the <strong>compressed air line used to cool optical instruments was visibly dripping oil</strong>. This air also communicated with the exhaust‑sampling environment, creating multiple, serious risks:
              </p>
              <ul className="mt-4 space-y-2">
                <li>Oil and particles contaminating <strong>high‑value optics</strong>, degrading data quality and potentially damaging lenses or housings.</li>
                <li>Oil carryover into the flame, <strong>artificially increasing NOx and other emissions</strong>, compromising test validity.</li>
                <li>Local burning of oil deposits near the optical tips, risking hardware distress.</li>
              </ul>
              <p className="mt-4">
                We immediately highlighted the issue and proposed a filtration solution tailored to the facility’s duty cycle and operational constraints.
              </p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OilFiltrationParticleRemoval;
