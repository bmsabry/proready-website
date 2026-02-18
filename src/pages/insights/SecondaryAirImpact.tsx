import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

const SecondaryAirImpact = () => {
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
              Jan 28, 2026
            </span>
          </div>

          <h1 className="text-4xl md:text-6xl font-bold mb-8 leading-tight">
            A Technical Deep Dive: Quantifying the Impact of Secondary Air on DLE Combustor Emissions
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
                href="/impact-of-secondary-air-on-emissions.pdf"
                download="impact-of-secondary-air-on-emissions.pdf"
                className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-6 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Download Full PDF
              </a>
            </div>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/impact-secondary-air-emissions.jpg" 
              alt="Secondary Air Impact Visualization" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed space-y-10">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Introduction: The Overlooked Variable in Emissions Control</h2>
              <p>
                The central challenge in modern Dry Low Emissions (DLE) combustion systems is the continuous drive to reduce Nitric Oxide (NOx) emissions while simultaneously managing critical operational constraints, such as the hardware cooling required for system durability. A key component of this balance is the use of "secondary air"—the portion of the total combustor airflow used for cooling, dilution, and managing leakage, which is distinct from the primary air that flows through the fuel-air premixer.
              </p>
              <p>
                While common engineering practice relates emissions performance to the theoretical mixer flame temperature (Tflame), the direct influence of this secondary air is not well-quantified in published literature. This represents a significant knowledge gap for designers aiming for single-digit NOx levels.
              </p>
              <p>
                This article presents a detailed analysis of a study that experimentally quantifies the impact of varying secondary air percentage on emissions, flame interaction, and thermo-acoustic stability. The experiments were conducted under the high-pressure, high-temperature conditions representative of an H class gas turbine, providing a practical and data-driven perspective on this critical design variable.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default SecondaryAirImpact;