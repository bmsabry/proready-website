import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';

const ImprovingGaseousFuelSupplySystemResponse = () => {
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
            Improving Gaseous Fuel Supply System Response
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/case-study-improving-gaseous-fuel-supply-system-response.pdf"
              download="case-study-improving-gaseous-fuel-supply-system-response.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/case-study-improving-gaseous-fuel-supply-system-response.jpg" 
              alt="Improving Gaseous Fuel Supply System Response" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Faster Fuel‑Flow Adjustment Across 10 Valves with 35 % Quicker Actuation and Reduced Downtime</h2>
              
              <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
              <p><strong>Industry:</strong> Aerospace / Combustion Test Facilities</p>
              <p><strong>Challenge:</strong> Slow valve response in a multi‑valve gaseous‑fuel system caused sluggish control, heavy recalibration workload, and efficiency loss during configuration changes.</p>
              <p><strong>Result:</strong> Ten electronically actuated control valves replaced the pneumatic set, improving flow‑adjustment response by ≈ 35 %, introducing auto‑calibration and durable trim materials, and enhancing overall system readiness.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>
              <p>
                A combustion‑test client needed its <strong>gaseous‑fuel delivery system</strong> to react more quickly and consistently during fuel‑flow transitions.
              </p>
              <p className="mt-4">
                The system comprised a <strong>family of about ten control valves</strong> operating together to stage and meter gaseous fuel to the combustor. Each valve’s slow response created a cascading delay through the entire manifold—limiting fine control and increasing setup time between tests.
              </p>
              <p className="mt-4">
                Technicians also faced frequent <strong>manual calibration and trim maintenance</strong>, extending downtime. While overall safety systems performed reliably, <strong>the main performance bottleneck was valve actuation speed</strong>—the ability to quickly, accurately adjust fuel flow during dynamic testing.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default ImprovingGaseousFuelSupplySystemResponse;
