import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';

const ExtendingEmissionsProbeDurability = () => {
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
            Extending Emissions Probe Durability
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/case-study-extending-emissions-probe-durability.pdf"
              download="case-study-extending-emissions-probe-durability.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/case-study-extending-emissions-rake-durability.jpg" 
              alt="Extending Emissions Probe Durability" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Enhancing Hardware Longevity in Harsh Test Environments</h2>
              
              <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
              <p><strong>Industry:</strong> Aerospace / Combustion Testing</p>
              <p><strong>Challenge:</strong> Frequent probe failures due to extreme thermal and mechanical stress during high-temperature emissions sampling.</p>
              <p><strong>Result:</strong> Significant extension of probe service life, reducing downtime and hardware replacement costs while maintaining high-fidelity data collection.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">The Challenge</h2>
              <p>
                Emissions probes operating in high-temperature exhaust streams are subject to intense thermal gradients and aerodynamic loads. In many test campaigns, these probes would fail prematurely, leading to costly test interruptions and the need for frequent hardware replacements.
              </p>
              <p className="mt-4">
                The objective was to redesign the probe cooling and structural support systems to withstand these conditions without interfering with the accuracy of the emissions samples being collected.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default ExtendingEmissionsProbeDurability;
