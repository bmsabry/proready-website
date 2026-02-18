import React from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Calendar, User, Tag, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';

const OptimizingTestCellAssembly = () => {
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
            Optimizing Test Cell Assembly
          </h1>

          <div className="flex items-center justify-end mb-12 pb-12 border-b border-slate-800">
            <a
              href="/case-study-optimizing-test-cell-assembly.pdf"
              download="CASE STUDY Optimizing Test Cell Assembly.pdf"
              className="inline-flex items-center justify-center rounded-full bg-cyan-500 px-8 py-4 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
            >
              Download Full PDF
            </a>
          </div>

          <div className="aspect-video rounded-3xl overflow-hidden mb-12">
            <img 
              src="/optimizing-test-cell-assembly.png" 
              alt="Optimizing Test Cell Assembly" 
              className="w-full h-full object-cover"
            />
          </div>

          <div className="prose prose-lg prose-invert max-w-none text-slate-300 leading-relaxed">
            <section>
              <h2 className="text-2xl md:text-3xl font-bold mb-6 text-white">1. Opening Hook – The Challenge</h2>
              <p>
                A major engine test facility faced long hardware assembly times that slowed every test campaign. Each program required roughly <strong>two weeks</strong> of setup before testing could begin—burning valuable schedule and resources. The customer’s target was simple but ambitious: <strong>cut assembly time noticeably without compromising quality or safety</strong>.
              </p>
            </section>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default OptimizingTestCellAssembly;
