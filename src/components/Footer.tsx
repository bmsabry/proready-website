import React from 'react';
import { Link } from 'react-router-dom';
import { Youtube, Mail, ArrowRight } from 'lucide-react';

const Footer = () => {
  return (
    <footer className="relative bg-slate-950 border-t border-slate-900 pt-16 pb-8 overflow-hidden">
      <div className="absolute inset-0 bg-grid-pattern bg-grid opacity-40 pointer-events-none" aria-hidden="true" />
      <div className="container-site relative">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-12 mb-14">
          <div className="md:col-span-4">
            <Link to="/" className="flex items-center space-x-3 mb-6">
              <img src="/Logo.jpg" alt="" width="32" height="32" className="h-8 w-auto rounded-md" loading="lazy" />
              <span className="font-display text-lg font-bold">ProReady<span className="text-cyan-400">Engineer</span></span>
            </Link>
            <p className="text-slate-400 text-sm leading-relaxed mb-6">
              Ex-GE, PhD-led consulting in gas turbine combustion, thermal fluid sciences,
              high-pressure test infrastructure, and industrial AI.
            </p>
            <div className="font-mono text-[11px] uppercase tracking-wider text-slate-500 space-y-1">
              <p>SAM.gov Small Business</p>
              <p>CAGE 18X84 &nbsp;•&nbsp; UEI RLHYXFN7JJN5</p>
              <p>NAICS 541330 • 611430 • 541611</p>
            </div>
          </div>

          <div className="md:col-span-3">
            <h2 className="text-white text-sm font-semibold uppercase tracking-wider mb-5">Expertise</h2>
            <ul className="space-y-3 text-sm text-slate-400">
              <li><Link to="/services" className="hover:text-cyan-400 transition-colors">Thermal Fluid Sciences</Link></li>
              <li><Link to="/services" className="hover:text-cyan-400 transition-colors">Gas Turbine Combustion</Link></li>
              <li><Link to="/services" className="hover:text-cyan-400 transition-colors">Industrial AI &amp; Data Analytics</Link></li>
              <li><Link to="/training" className="hover:text-cyan-400 transition-colors">Training &amp; Workshops</Link></li>
            </ul>
          </div>

          <div className="md:col-span-2">
            <h2 className="text-white text-sm font-semibold uppercase tracking-wider mb-5">Company</h2>
            <ul className="space-y-3 text-sm text-slate-400">
              <li><Link to="/case-studies" className="hover:text-cyan-400 transition-colors">Case Studies</Link></li>
              <li><Link to="/insights" className="hover:text-cyan-400 transition-colors">Research Insights</Link></li>
              <li><Link to="/testimonials" className="hover:text-cyan-400 transition-colors">Testimonials</Link></li>
              <li><Link to="/contact" className="hover:text-cyan-400 transition-colors">Contact Us</Link></li>
            </ul>
          </div>

          <div className="md:col-span-3">
            <h2 className="text-white text-sm font-semibold uppercase tracking-wider mb-5">Start a Conversation</h2>
            <p className="text-slate-400 text-sm mb-4">Tell us about your toughest technical problem.</p>
            <Link to="/contact" className="btn-ghost mb-6">
              Get in touch <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </Link>
            <div className="flex space-x-3 mt-4">
              <a href="https://www.youtube.com/@ProReadyEngineer" target="_blank" rel="noopener noreferrer" aria-label="ProReadyEngineer on YouTube" className="p-2 bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors text-slate-400 hover:text-cyan-400">
                <Youtube className="w-5 h-5" aria-hidden="true" />
              </a>
              <a href="mailto:info@proreadyengineer.com" aria-label="Email ProReadyEngineer" className="p-2 bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors text-slate-400 hover:text-cyan-400">
                <Mail className="w-5 h-5" aria-hidden="true" />
              </a>
            </div>
          </div>
        </div>

        <div className="border-t border-slate-900 pt-8 flex flex-col sm:flex-row justify-between items-center gap-4 text-xs text-slate-500">
          <p>© {new Date().getFullYear()} ProReadyEngineer LLC. All rights reserved.</p>
          <p className="font-mono text-[11px]">Engineering the future of energy — combustion • hydrogen • AI</p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
