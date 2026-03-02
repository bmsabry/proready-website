import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

const ReinstatementOfPolypropylenePlantHighPressureBlowDownVessel = () => {
  return (
    <div className="pt-32 pb-20">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <Link to="/case-studies" className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 transition-colors mb-12 group">
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Case Studies
        </Link>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <h1 className="text-4xl md:text-6xl font-bold mb-8 leading-tight">
            Reinstatement of Polypropylene Plant – High Pressure Blow Down Vessel
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/Reinstatement_of_Polypropylene_Plant_High_Pressure_Blow_Down_Vessel.pdf"
              download="Reinstatement_of_Polypropylene_Plant_High_Pressure_Blow_Down_Vessel.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img
              src="/Reinstatement_of_Polypropylene_Plant_High_Pressure_Blow_Down_Vessel.png"
              alt="Reinstatement of Polypropylene Plant – High Pressure Blow Down Vessel"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <p className="text-xl font-semibold text-white mb-6">
                Emergency Fabrication of a 145-Metric-Ton Pressure Vessel Under Tight Schedule and Complex Design Constraints
              </p>

              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Project Snapshot</h2>
              <ul className="mt-4 space-y-2">
                <li><strong>Industry:</strong> Petrochemical / Pressure Vessel Fabrication</li>
                <li><strong>Location:</strong> Yanbu, Kingdom of Saudi Arabia</li>
                <li><strong>Client:</strong> NATPET (National Petrochemical Company) / Tecnimont</li>
                <li><strong>Fabricated By:</strong> Hidada Ltd., Jeddah, KSA</li>
                <li><strong>Challenge:</strong> Post-explosion plant reinstatement requiring urgent fabrication of a complex, heavy-wall pressure vessel under an exceptionally tight engineering and delivery schedule.</li>
                <li><strong>Result:</strong> Successfully designed, fabricated, inspected, and delivered a code-compliant 145-metric-ton High Pressure Blow Down Vessel to reinstate plant operations.</li>
              </ul>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>
              <p>
                In 2018, a significant explosion at NATPET's polypropylene facility in Yanbu, KSA forced a <strong>complete plant shutdown</strong>, halting production and creating enormous financial and operational pressure to restore operations as quickly as possible.
              </p>
              <p>
                Three critical pressure vessels were damaged beyond repair and needed to be <strong>replaced with newly fabricated equipment</strong>. All three—<strong>D-601, D-602, and D-603</strong>—were awarded to <strong>Hidada Ltd.</strong>, with D-601 representing the most complex and demanding fabrication challenge in the program.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default ReinstatementOfPolypropylenePlantHighPressureBlowDownVessel;
