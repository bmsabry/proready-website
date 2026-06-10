import React from 'react';
import { ArrowLeft, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

import { usePageMeta } from '../../lib/meta';
const bassamImg = '/Bassam.jpg';
const hydrogenImg = '/Hydrogen_Impact_on_Combustor_Performance_and_NOx_Emissions.jpg';

const TransitioningDLECombustionSystemsTo100Hydrogen = () => {
  usePageMeta('DLE Combustion Systems on 100% Hydrogen', 'The physics of hydrogen transition in DLE gas turbines: laminar flame speed, flashback propensity, and the limits of moving from natural gas to 100% hydrogen.');

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
              Feb 20, 2026
            </span>
          </div>

          <h1 className="text-3xl md:text-5xl font-bold mb-8 leading-tight">
            Transitioning DLE Combustion Systems to 100% Hydrogen Operation
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
                href="/ProReady_Transitioning DLE Combustion Systems to 100% Hydrogen Operation.pdf"
                download="Transitioning DLE Combustion Systems to 100% Hydrogen Operation.pdf"
                className="btn-primary rounded-full"
              >
                Download Full PDF
              </a>
            </div>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img loading="lazy" decoding="async" 
              src={hydrogenImg} 
              alt="Transitioning DLE Combustion Systems to 100% Hydrogen Operation" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed space-y-10">
            <section>
              <h3 className="text-xl md:text-2xl font-bold mb-4 text-cyan-400">1. The Physics of Hydrogen Transition: Flame Speed and Flashback Propensity</h3>
              <p>
                As the global energy landscape pivots toward a hydrogen economy, the aerospace and power generation sectors face a fundamental strategic necessity: redefining the kinetic boundaries of existing gas turbine hardware. Central to this transition is the understanding of laminar flame speed (S<sub>L</sub>). For a Principal Engineer, S<sub>L</sub> is not merely a laboratory metric; it is the primary determinant of hardware safety and the "kinetic firewall" against catastrophic failure. In the transition from Natural Gas (methane) to Hydrogen, S<sub>L</sub> dictates how quickly the fuel-air mixture is consumed and, crucially, whether the flame can propagate upstream into the injection hardware—an event known as flashback.
              </p>
              <p>
                Research leveraging the Cantera perfectly stirred reactor (PSR) network model reveals that hydrogen's laminar flame speed can be up to 50 times higher than that of methane. This massive increase fundamentally alters the risk profile for industrial mixers. As the equivalence ratio (&phi;) increases, the ratio of hydrogen flame speed to methane flame speed rises sharply, indicating that richer mixtures are exponentially more susceptible to flashback and flame-holding events.
              </p>
              <p>
                When evaluating combustion architectures, Dry Low Emissions (DLE) systems demonstrate a clear strategic advantage over Rich-Quench-Lean (RQL) or diffusion-based systems. DLE systems typically operate at low equivalence ratios (often &phi; &lt; 0.75), where the increase in flame speed is significantly more modest compared to the high-equivalence-ratio zones inherent in RQL designs. By maintaining a lean environment, DLE hardware provides a higher margin of safety against hydrogen-related flashback. However, while steady-state flame speeds define the boundaries of operation, the transient risks of flame holding must be quantified using the Blow Off Time (BOT) metric.
              </p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TransitioningDLECombustionSystemsTo100Hydrogen;