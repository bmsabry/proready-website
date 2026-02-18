import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';

const EnhancingTestExecutionCostEfficiency = () => {
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
            Enhancing Test Execution Cost & Efficiency
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/case-study-enhancing-test-execution-cost-efficiency.pdf"
              download="CASE STUDY Enhancing Test Execution Cost & Efficiency.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/case2-study-enhancing-test-execution-cost-efficiency.jpg" 
              alt="Enhancing Test Execution Cost & Efficiency" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">CASE STUDY: Enhancing Test Execution Efficiency</h2>
              <p className="text-cyan-400 font-semibold text-lg mb-6">Improving Data Quality and Increasing Throughput by 40%</p>
              
              <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
              <p><strong>Industry:</strong> Aerospace / Combustion Engineering</p>
              <p><strong>Challenge:</strong> Manual test operations led to limited data capture, post‑processing delays, and repeat testing.</p>
              <p><strong>Result:</strong> 40% increase in daily data points, 50% staffing reduction per test, and $2M of savings over 10 years ({'>'} $10M potential across five cells).</p>
            </section>

            <section className="mt-12">
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>
              <p>
                A major aerospace test organization sought to improve the <strong>efficiency and quality</strong> of their combustion test campaigns. Each test day required collecting about <strong>40 distinct data points</strong> over <strong>6–8 hours</strong>, running roughly <strong>two tests per week</strong>. Post‑processing consumed another full day due to data alignment issues, and <strong>15% of data points required repetition</strong>.
              </p>
              <p className="mt-4">The goals were to:</p>
              <ul>
                <li>Increase valid daily data points by <strong>{'≥'} 20%</strong></li>
                <li>Eliminate post‑processing delays</li>
                <li>If possible, Reduce manpower and improve test repeatability</li>
              </ul>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default EnhancingTestExecutionCostEfficiency;
