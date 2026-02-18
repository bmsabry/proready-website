import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

const TestAssetProtectionLogic = () => {
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
            Protecting Millions: Smart Logic for Combustion Testing Failures
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/Test_Asset_Protection_Logic.pdf"
              download="Test_Asset_Protection_Logic.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img
              src="/Test_Asset_Protection_Logic.jpg"
              alt="Test Asset Protection Logic"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">Protecting Seven‑Figure Programs and Six‑Figure Test Articles Through Smart Emergency Shutdown Design</h2>
              
              <h3 className="text-xl font-bold mb-4 text-white">Project Snapshot</h3>
              <p><strong>Industry:</strong> Aerospace / Combustion Testing</p>
              <p><strong>Challenge:</strong> High‑value combustion test articles (hundreds of thousands of dollars each) were exposed to multiple failure scenarios with potential for catastrophic damage.</p>
              <p><strong>Result:</strong> A structured, automated protection logic that sequences dozens of control elements during emergencies, dramatically improving safety, preserving assets, and stabilizing test operations.</p>
            </section>

            <hr className="border-slate-800 my-12" />

            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>
              <p>
                In advanced combustion testing, the real challenge is not just running a test; it is <strong>protecting a very expensive test article</strong> every second the flame is on. A single adverse event can melt metal, crack components, or destroy a unique prototype in minutes.
              </p>
              <p className="mt-4">
                The lab environment is full of what‑ifs: loss of air, control‑valve failure, acoustic overload, fuel spikes, or quench‑system faults. The question we set out to answer was: <strong>How do we guarantee that when something abnormal happens, the test article survives undamaged?</strong>
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default TestAssetProtectionLogic;
