import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

const SACDynamics = () => {
  return (
    <div className="pt-32 pb-20">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <Link to="/insights" className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 transition-colors mb-12 group">
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Research Insights
        </Link>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <div className="flex items-center gap-4 mb-6">
            <span className="flex items-center gap-1.5 text-xs font-medium text-cyan-400 uppercase tracking-wider">
              <Tag className="w-3 h-3" />
              Technical Analysis
            </span>
            <span className="text-slate-600">•</span>
            <span className="flex items-center gap-1.5 text-xs text-slate-500">
              <Calendar className="w-3 h-3" />
              Jan 26, 2026
            </span>
          </div>

          <h1 className="text-4xl md:text-6xl font-bold mb-8 leading-tight">
            Technical Analysis of Combustion Dynamics in Single Annular Combustor (SAC) Sectors
          </h1>

          <div className="flex items-center justify-between gap-4 mb-12 pb-12 border-b border-slate-800">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center overflow-hidden">
                <img src="/Bassam.jpg" alt="Dr. Bassam Abdelnabi" className="w-full h-full object-cover" />
              </div>
              <div>
                <p className="text-sm font-bold text-slate-200">Dr. Bassam Abdelnabi</p>
                <p className="text-xs text-slate-500">Principal Consultant, Gas Turbine Combustion Expert</p>
              </div>
            </div>
            <div>
              <a
                href="/SAC Dynamics.pdf"
                download="SAC Dynamics.pdf"
                className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-6 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Download Full PDF
              </a>
            </div>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/SAC_Dynamics.jpg" 
              alt="Combustion Dynamics in SAC Sectors" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed space-y-10">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Introduction to Thermo-Acoustic Instabilities</h2>
              <p>
                Thermo-acoustic instabilities represent a significant obstacle in the advancement of lean-premixed gas turbine technology. These phenomena are governed by the constructive coupling between unsteady heat release (q') and acoustic pressure oscillations (p'), as described by the <strong>Rayleigh Criterion</strong>.
              </p>
              <p>
                When these fluctuations occur in phase, the acoustic field extracts energy from the combustion process, leading to high-amplitude pressure pulsations. 
              </p>
              <p>
                In modern swirl-stabilized systems, these instabilities are driven by:
              </p>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>Feed-coupling mechanisms:</strong> Equivalence ratio oscillations at the burner inlet.</li>
                <li><strong>Hydrodynamic instabilities:</strong> Vortex shedding and swirling flow periodicity.</li>
              </ul>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default SACDynamics;