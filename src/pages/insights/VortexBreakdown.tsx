import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

const VortexBreakdown = () => {
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
              Jan 25, 2026
            </span>
          </div>

          <h1 className="text-4xl md:text-6xl font-bold mb-8 leading-tight">
            Decoding the Vortex: A Technical Deep-Dive into Breakdown Dynamics and Stability
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
                href="/Vortex_Break_Down.pdf"
                download="Vortex_Break_Down.pdf"
                className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-6 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Download Full PDF
              </a>
            </div>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/Vortex_Break_Down_Image.png" 
              alt="Vortex Breakdown Visualization" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed space-y-10">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Introduction: The Mechanics of the "Vortex Breakdown"</h2>
              <p>
                In the rigorous analysis of high-speed fluid mechanics, "vortex breakdown" is defined as a abrupt and drastic change in the structure of a swirling flow. As fundamentally articulated by Leibovich, this phenomenon is initiated by specific variations in the tangential-to-axial velocity ratios. Physically, it manifests as a sudden retardation of the axial flow, culminating in the formation of stagnation points and complex recirculation zones.
              </p>
              <p>
                The engineering relevance of vortex breakdown is bifurcated. In aeronautical applications, it represents a catastrophic stability hazard; for instance, the breakdown of leading-edge vortices on delta wings—governed by the angle of attack—can cause a sudden shift in the aerodynamic center and loss of lift. Conversely, in the propulsion sector, breakdown is an essential mechanism for flame stabilization. The resulting internal recirculation zone (IRZ) acts as a high-temperature aerodynamic bluff body, ensuring continuous ignition and stable heat release in high-intensity combustion systems. This synthesis evaluates the mechanical thresholds, numerical evolution, and enstrophy intensification associated with this transition, drawing upon 45 years of experimental and computational research.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default VortexBreakdown;