import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

const RecoveryReactorFeedCoolerHeatExchanger = () => {
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
            Recovery Reactor Feed Cooler Heat Exchanger
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/Recovery_Reactor_Feed_Cooler_Heat_Exchanger.pdf"
              download="Recovery_Reactor_Feed_Cooler_Heat_Exchanger.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img
              src="/Recovery_Reactor_Feed_Cooler_Heat_Exchanger.jpg"
              alt="Recovery Reactor Feed Cooler Heat Exchanger"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <p className="text-xl font-bold text-white mb-6">Precision Thermal Design for a Critical Process Stream in a Chemically Aggressive Environment</p>

            <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
            <ul className="mt-4 space-y-2">
              <li><strong>Industry:</strong> Petrochemical / Process Equipment</li>
              <li><strong>Equipment Type:</strong> Shell and Tube Heat Exchanger</li>
              <li><strong>Service:</strong> Recovery Reactor Feed Cooler</li>
              <li><strong>Design Code:</strong> ASME Section VIII Division 1, 2019 Edition</li>
              <li><strong>Standards:</strong> TEMA 10th Edition, 2019 + API 660 9th Edition</li>
              <li><strong>TEMA Type:</strong> BFU</li>
              <li><strong>Material:</strong> Stainless Steel TP316L</li>
              <li><strong>Challenge:</strong> Design and deliver a reliable, code-compliant feed cooler capable of conditioning a chemically sensitive reactor feed stream while resisting corrosion in a demanding process environment.</li>
              <li><strong>Result:</strong> A fully engineered, ASME-compliant heat exchanger meeting TEMA BFU and API 660 requirements, fabricated in SS TP316L for long-term corrosion resistance and process integrity.</li>
            </ul>

            <hr className="border-slate-800 my-12" />

            <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook &#8211; The Challenge</h2>
            <p>In petrochemical processing, the condition of a reactor feed stream is critical. Feed temperature directly influences <strong>reaction selectivity, yield, and catalyst life</strong>. Delivering feed at the wrong temperature&#8212;even temporarily&#8212;can cause runaway reactions, catalyst degradation, or unsafe operating conditions.</p>
            <p className="mt-4">This project required the engineering and fabrication of a <strong>Recovery Reactor Feed Cooler</strong>, a heat exchanger tasked with precisely conditioning the process stream before it enters the reactor. The challenge was not just thermal performance&#8212;it was delivering that performance <strong>reliably, safely, and durably</strong> in a chemically aggressive environment where material selection, code compliance, and mechanical integrity were non-negotiable.</p>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default RecoveryReactorFeedCoolerHeatExchanger;
