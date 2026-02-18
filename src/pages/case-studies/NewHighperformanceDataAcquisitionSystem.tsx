import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

const NewHighperformanceDataAcquisitionSystem = () => {
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
            New High‑Performance Data Acquisition System
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/New_HighPerformance_Data_Acquisition_System.pdf"
              download="New_HighPerformance_Data_Acquisition_System.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img
              src="/New_HighPerformance_Data_Acquisition_System.jpg"
              alt="New High‑Performance Data Acquisition System"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <p className="text-xl text-white font-semibold mb-6">
              <strong>From Decades‑Old Bottleneck to Dynamic, Test‑Engineer‑Driven Tool in 12 Weeks</strong>
            </p>

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Project Snapshot</h2>

              <p><strong>Industry:</strong> Aerospace / Combustion Testing<br/>
              <strong>Challenge:</strong> Legacy data acquisition system created delays, data‑loss risks, and dependency on one specialist, costing tens of thousands weekly in lost productivity.<br/>
              <strong>Result:</strong> A modern, customizable GUI platform with auto‑saving, Excel integration, and on‑the‑fly configuration—delivered as a minimum viable product in 3 weeks, fully functional in 12 weeks.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>

              <p>A major test facility relied on a <strong>decades‑old data acquisition system</strong> managed by a single specialist. While it collected basic data, it couldn't keep pace with evolving test requirements or late‑shift operations.</p>

              <p>Engineers faced:</p>

              <ul className="mt-4 space-y-2 ml-6">
                <li><strong>No ability to make changes</strong> without the specialist on‑site.</li>
                <li><strong>Static executables</strong> requiring recompilation and redeployment for any tweak.</li>
                <li><strong>Critical calculations</strong> becoming inaccurate mid‑test, with no quick fix.</li>
                <li><strong>Data‑loss incidents</strong> from forgotten manual "record" clicks.</li>
              </ul>

              <p className="mt-6">These constraints translated to <strong>tens of thousands of dollars lost weekly</strong> in stalled testing, delayed insights, and wasted cell time.</p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default NewHighperformanceDataAcquisitionSystem;
