import React from 'react';
import { ArrowLeft, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

import { usePageMeta } from '../../lib/meta';
const bassamImg = '/Bassam.jpg';
const aerodynamicsImg = '/SAC_Aerodynamics.jpg';

const SACAerodynamics = () => {
  usePageMeta('Aerodynamics of a Single Annular Combustor', 'Experimental investigation of the aerodynamics within a realistic Single Annular Combustor sector and their role in combustion stability, emissions, and dynamics.');

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <Link to="/insights" className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 transition-colors mb-12 group">
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Research Insights
        </Link>

        <div className="anim-enter">
          <div className="flex items-center gap-4 mb-6">
            <span className="flex items-center gap-1.5 text-xs font-medium text-cyan-400 uppercase tracking-wider">
              <Tag className="w-3 h-3" />
              Technical Analysis
            </span>
            <span className="text-slate-600">•</span>
            <span className="flex items-center gap-1.5 text-xs text-slate-400">
              <Calendar className="w-3 h-3" />
              Jan 26, 2026
            </span>
          </div>

          <h1 className="text-3xl md:text-5xl font-bold mb-8 leading-tight">
            Aerodynamics of a Single Annular Combustor
          </h1>

          <div className="flex items-center justify-between gap-4 mb-12 pb-12 border-b border-slate-800">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center overflow-hidden">
                <img loading="lazy" decoding="async" src={bassamImg} alt="Dr. Bassam Abdelnabi" className="w-full h-full object-cover" />
              </div>
              <div>
                <p className="text-sm font-bold text-slate-200">Dr. Bassam Abdelnabi</p>
                <p className="text-xs text-slate-400">Principal Consultant, Gas Turbine Combustion Expert</p>
              </div>
            </div>
            <div>
              <a
                href="/SAC Aerodynamics.pdf"
                download="SAC Aerodynamics.pdf"
                className="btn-primary rounded-full"
              >
                Download Full PDF
              </a>
            </div>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img loading="lazy" decoding="async" 
              src={aerodynamicsImg} 
              alt="Aerodynamics of a Single Annular Combustor" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed space-y-10">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">A Technical Deep Dive: Analyzing the Aerodynamics of a Gas Turbine Combustor Sector</h2>
              <h3 className="text-xl md:text-2xl font-bold mb-4 text-cyan-400">Introduction: The Critical Role of Aerodynamics in Combustor Design</h3>
              <p>
                This analysis details the experimental investigation of aerodynamics within a realistic Single Annular Combustor (SAC) sector, also known as a Fuel Rich Dome Combustor. In the design and development of Gas Turbine Combustors (GTC), aerodynamics are of the first priority, playing a vital role in combustion stability, emissions, and overall dynamics.
              </p>
              <p>
                This article will focus specifically on the experimental methodology used and the key numerical findings from the study, which are based on Laser Doppler Velocimetry (LDV) and Particle Image Velocimetry (PIV) measurements.
              </p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SACAerodynamics;