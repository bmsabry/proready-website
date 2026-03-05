import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

const ImpactOfOperationalModes = () => {
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
              Mar 5, 2026
            </span>
          </div>

          <h1 className="text-4xl md:text-6xl font-bold mb-8 leading-tight">
            The Critical Impact of Operational Modes on Gas Turbine Combustor Performance
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
                href="/ProReady_Impact_of_Operational_Modes_on_Gas_Turbine_Combustor_Performance.pdf"
                download="ProReady_Impact_of_Operational_Modes_on_Gas_Turbine_Combustor_Performance.pdf"
                className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-6 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Download Full PDF
              </a>
            </div>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img
              src="/Impact_of_Operational_Modes_on_Gas_Turbine_Combustor_Performance.jpg"
              alt="Operational Modes Impact Visualization"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed space-y-10">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Introduction: The Thermal Challenge of Liner Durability</h2>
              <p>
                In the pursuit of increased power density and thermal efficiency, liner durability has solidified as the primary technical bottleneck for gas turbine longevity. The mechanical integrity of the combustor hardware is dictated by the synergy between absolute maximum metal temperatures and steep temperature gradients, which together catalyze mechanical stress and material fatigue. A pivotal 2012 investigation analyzed these variables, demonstrating that the "mode of operation"—defined by fuel phase and injection method—is the dominant driver of liner life.
              </p>
              <p>
                This research provides an analytical evaluation of how non-premixed natural gas, dry liquid fuel, and wet liquid fuel modes influence localized heat loading, emissions profiles, and acoustic operability. Analysis of these high-fidelity experimental data points yields essential design parameters for predicting hardware degradation and managing operational margins in F-class systems.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default ImpactOfOperationalModes;
