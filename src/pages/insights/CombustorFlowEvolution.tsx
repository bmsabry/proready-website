import React from 'react';
import { ArrowLeft, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

import { usePageMeta } from '../../lib/meta';
const bassamImg = '/Bassam.jpg';
const flowEvolutionImg = '/SAC_Flow_Evolution.jpg';

const CombustorFlowEvolution = () => {
  usePageMeta('Combustor Flow Structure Evolution Analysis', 'Experimental analysis of how the internal flow field and central recirculation zone evolve in a gas turbine combustor, governing flame stability and emissions.');

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
            An Experimental Analysis of Combustor Flow Structure Evolution
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
                href="/SAC_Flow_Structure_Evolution.pdf"
                download="SAC_Flow_Structure_Evolution.pdf"
                className="btn-primary rounded-full"
              >
                Download Full PDF
              </a>
            </div>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img loading="lazy" decoding="async" 
              src={flowEvolutionImg} 
              alt="Combustor Flow Structure Evolution" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed space-y-10">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Introduction: The Aerodynamics of Combustion</h2>
              <p>
                In the design of Gas Turbine Combustors (GTC), aerodynamics—specifically the structure of the internal flow field—plays a critical role in ensuring flame stability and managing pollutant emissions. The primary mechanism for flame anchoring is the establishment of a Central Recirculation Zone (CRZ), a region of reverse flow that continuously ignites the incoming fuel-air mixture.
              </p>
              <p>
                This study presents an experimental investigation into how modifications to the combustion chamber geometry can be used to control the flow field structure. The analysis of the resulting aerodynamic changes was conducted using two-component Laser Doppler Velocimetry (LDV).
              </p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CombustorFlowEvolution;