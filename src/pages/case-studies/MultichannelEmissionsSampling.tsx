import React from 'react';
import { ArrowLeft, Calendar, User, Tag, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import { usePageMeta } from '../../lib/meta';
const MultichannelEmissionsSampling = () => {
  usePageMeta('Multichannel Emissions Sampling System Case Study', 'A fully functional multichannel emissions sampling system delivered in 8 weeks at 38% of the quoted cost, saving about $50K per unit.');

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <Link to="/case-studies" className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 transition-colors mb-12 group">
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Case Studies
        </Link>

        <div className="anim-enter">
          <h1 className="text-3xl md:text-5xl font-bold mb-8 leading-tight">
            Innovative system that enables multichannel emissions sampling
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/case-study-enabling-multichannel-emissions-sampling.pdf"
              download="case-study-enabling-multichannel-emissions-sampling.pdf"
              className="btn-primary rounded-full"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img loading="lazy" decoding="async" 
              src="/case-study-enabling-multichannel-emissions-sampling.jpg" 
              alt="Innovative system that enables multichannel emissions sampling" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Delivering a Faster, Simpler, and 62% Cheaper Solution in Eight Weeks</h2>
              
              <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
              <p><strong>Industry:</strong> Aerospace / Combustion Emissions Testing</p>
              <p><strong>Challenge:</strong> A high-cost, four-month lead-time design hindered timely emissions measurement upgrades.</p>
              <p><strong>Result:</strong> Fully functional system delivered in 8 weeks at 38% of the quoted cost, saving ≈ $50 K per unit and meeting all technical and accuracy requirements.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>
              <p>
                A major combustion test facility needed a <strong>multichannel emissions sampling system</strong> capable of reading from individual exhaust probes and also measuring a <strong>combined total-average sample</strong>. The goal was to quickly connect twelve sampling ports at the exhaust outlet and route each to the emissions analyzer without compromising accuracy of NOx, CO, and CO₂ measurements.
              </p>
              <p className="mt-4">
                The customer’s initial engineering proposal, developed by a third party, quoted an <strong>$80 K system</strong> with a <strong>four‑month delivery</strong>, which was unacceptable given the test program schedule. Their target: <strong>complete installation in 8 weeks</strong> with comparably high measurement fidelity.
              </p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MultichannelEmissionsSampling;
