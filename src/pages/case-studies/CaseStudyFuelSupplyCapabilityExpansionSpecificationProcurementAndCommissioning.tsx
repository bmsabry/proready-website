import React from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

import { usePageMeta } from '../../lib/meta';
const CaseStudyFuelSupplyCapabilityExpansionSpecificationProcurementAndCommissioning = () => {
  usePageMeta('Fuel Supply Capability Expansion Case Study', 'How a multi-fuel supply system (CNG, nitrogen, propane) was specified, procured, and commissioned to deliver flows the existing infrastructure could not support.');

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <Link to="/case-studies" className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 transition-colors mb-12 group">
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Case Studies
        </Link>

        <div className="anim-enter">
          <h1 className="text-3xl md:text-5xl font-bold mb-8 leading-tight">
            Fuel Supply Capability Expansion – Specification, Procurement, and Commissioning
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/CASE_STUDY_Fuel_Supply_Capability_Expansion__Specification_Procurement_and_Commissioning.pdf"
              download="Fuel Supply Capability Expansion – Specification, Procurement, and Commissioning.pdf"
              className="btn-primary rounded-full"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img loading="lazy" decoding="async"
              src="/CASE_STUDY_Fuel_Supply_Capability_Expansion__Specification_Procurement_and_Commissioning.jpg"
              alt="Fuel Supply Capability Expansion – Specification, Procurement, and Commissioning"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <p className="text-xl text-white font-semibold mb-6">
              <strong>Delivering High‑Flow Natural Gas, Nitrogen Doping, and Propane Blending from Design to Operational Use</strong>
            </p>

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Project Snapshot</h2>

              <p><strong>Industry:</strong> Aerospace / Combustion Test Facilities<br/>
              <strong>Challenge:</strong> The test site needed higher natural‑gas flow than the utility could supply, plus new capabilities for nitrogen doping and propane blending, none of which the existing infrastructure could support.<br/>
              <strong>Result:</strong> A fully <strong>specified, procured, and commissioned</strong> multi‑fuel supply solution (CNG + nitrogen + propane) that safely delivers the required flows and mixtures, after correcting critical sizing and specification gaps.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>

              <p>A test site needed to run <strong>higher‑flow natural‑gas tests</strong> and explore <strong>variable gas compositions</strong> (nitrogen‑diluted gas and propane‑enriched fuel). The client had already invested in a <strong>new million‑dollar gas compressor</strong>, expecting it to unlock the required capacity.</p>

              <p>However, the tests still couldn't run at the desired conditions, and nitrogen doping or propane blending <strong>weren't possible at all</strong> with the existing infrastructure. The goal of this project was to <strong>enable an entirely new fuel‑supply capability</strong> through complete <strong>specification, procurement, and commissioning</strong>.</p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CaseStudyFuelSupplyCapabilityExpansionSpecificationProcurementAndCommissioning;
