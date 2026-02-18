import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';

const DualModeLiquidFuelPumpingSystem = () => {
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
            Specifying, Procuring, and Installing a Dual‑Mode Liquid‑Fuel Pumping System
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/case-study-specifying-procuring-and-installing-a-dualmode-liquidfuel-pumping-system.pdf"
              download="case-study-specifying-procuring-and-installing-a-dualmode-liquidfuel-pumping-system.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/case-study-specifying-procuring-and-installing-a-dualmode-liquidfuel-pumping-system.jpg" 
              alt="Dual-Mode Liquid-Fuel Pumping System" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Building Reliability by Engineering for Performance and Emergency Readiness</h2>
              
              <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
              <p><strong>Industry:</strong> Aerospace / Combustion Systems Integration</p>
              <p><strong>Challenge:</strong> Deliver a high‑pressure liquid‑fuel pumping system capable of both dry‑fuel and fuel‑water emulsion operation.</p>
              <p><strong>Result:</strong> Fully integrated three‑stage skid designed, procured, and commissioned with advanced control, redundancy, and purge safety—meeting precise duty targets while ensuring safe emergency response.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Mission</h2>
              <p>
                This project didn’t begin with a failure to fix—it began with a <strong>capability to enable</strong>. The client required a new <strong>liquid‑fuel pumping system</strong> that could operate in both <strong>dry</strong> and <strong>emulsified fuel modes</strong> to expand their combustion‑test flexibility.
              </p>
              <p className="mt-4">
                The target duty parameters were challenging—pressures exceeding <strong>3,000 psi</strong>, at a flow rate of <strong>1500 lb/hr</strong>, feeding six independently staged fuel circuits, and the ability to run cleanly in standard liquid‑fuel mode or mix fuel with water to form a controlled emulsion for emissions control testing.
              </p>
              <p className="mt-4">
                Equally important, the system needed to perform <strong>safely and predictably under emergency conditions</strong>, where loss of control could mean damage worth hundreds of thousands of dollars.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default DualModeLiquidFuelPumpingSystem;
