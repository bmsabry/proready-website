import React from 'react';
import { Link } from 'react-router-dom';
import { Youtube, Mail, ArrowRight } from 'lucide-react';

const FooterHeading = ({ children }: { children: React.ReactNode }) => (
  <h2 className="text-xs font-mono font-semibold uppercase tracking-[0.18em] text-slate-400 mb-6">
    {children}
  </h2>
);

const FooterLink = ({ to, children }: { to: string; children: React.ReactNode }) => (
  <li>
    <Link to={to} className="text-sm text-slate-300 hover:text-cyan-400 transition-colors">
      {children}
    </Link>
  </li>
);

const Footer = () => {
  return (
    <footer className="relative bg-slate-950 border-t border-slate-900 overflow-hidden">
      <div className="absolute inset-0 bg-grid-pattern bg-grid opacity-40 pointer-events-none" aria-hidden="true" />
      <div className="container-site relative pt-16 lg:pt-20 pb-8">

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-[1.6fr_1fr_0.9fr_1.3fr] gap-x-10 gap-y-12">

          {/* Brand */}
          <div className="sm:col-span-2 lg:col-span-1 lg:pr-6">
            <Link to="/" className="inline-flex items-center gap-3 mb-5">
              <img src="/Logo.jpg" alt="" width="36" height="36" className="h-9 w-auto rounded-md" loading="lazy" />
              <span className="font-display text-lg font-bold">
                ProReady<span className="text-cyan-400">Engineer</span>
              </span>
            </Link>
            <p className="text-sm text-slate-300 leading-relaxed max-w-sm mb-6">
              Ex-GE, PhD-led consulting in gas turbine combustion, thermal fluid sciences,
              high-pressure test infrastructure, and industrial AI.
            </p>
            <div className="font-mono text-xs leading-6 uppercase tracking-wider text-slate-300 space-y-1">
              <p>SAM.gov Small Business</p>
              <p>CAGE 18X84 · UEI RLHYXFN7JJN5</p>
              <p>NAICS 541330 · 611430 · 541611</p>
            </div>
          </div>

          {/* Expertise */}
          <nav aria-label="Expertise">
            <FooterHeading>Expertise</FooterHeading>
            <ul className="space-y-3.5">
              <FooterLink to="/services/gas-turbine-combustion">Gas Turbine Combustion</FooterLink>
              <FooterLink to="/services/test-cell-design">Test Cell Design &amp; Commissioning</FooterLink>
              <FooterLink to="/services/industrial-ai">Industrial AI &amp; Data Analytics</FooterLink>
              <FooterLink to="/services">All Services</FooterLink>
              <FooterLink to="/training">Training &amp; Workshops</FooterLink>
              <FooterLink to="/learn">Learner Sign In</FooterLink>
            </ul>
          </nav>

          {/* Company */}
          <nav aria-label="Company">
            <FooterHeading>Company</FooterHeading>
            <ul className="space-y-3.5">
              <FooterLink to="/case-studies">Case Studies</FooterLink>
              <FooterLink to="/insights">Research Insights</FooterLink>
              <FooterLink to="/testimonials">Testimonials</FooterLink>
              <FooterLink to="/contact">Contact Us</FooterLink>
            </ul>
          </nav>

          {/* CTA */}
          <div>
            <FooterHeading>Start a Conversation</FooterHeading>
            <p className="text-sm text-slate-300 leading-relaxed mb-5">
              Tell us about your toughest technical problem.
            </p>
            <Link to="/contact" className="btn-secondary px-5 py-2.5 text-sm mb-7">
              Get in touch <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </Link>
            <div className="flex gap-3">
              <a
                href="https://www.youtube.com/@ProReadyEngineer"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="ProReadyEngineer on YouTube"
                className="p-2.5 bg-slate-900 border border-slate-800 rounded-lg hover:border-slate-600 hover:bg-slate-800 transition-colors text-slate-300 hover:text-cyan-400"
              >
                <Youtube className="w-5 h-5" aria-hidden="true" />
              </a>
              <a
                href="mailto:info@proreadyengineer.com"
                aria-label="Email ProReadyEngineer"
                className="p-2.5 bg-slate-900 border border-slate-800 rounded-lg hover:border-slate-600 hover:bg-slate-800 transition-colors text-slate-300 hover:text-cyan-400"
              >
                <Mail className="w-5 h-5" aria-hidden="true" />
              </a>
            </div>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="mt-14 lg:mt-16 pt-7 border-t border-slate-800/70 flex flex-col-reverse sm:flex-row items-center justify-between gap-3 text-xs text-slate-400">
          <p>© {new Date().getFullYear()} ProReadyEngineer LLC. All rights reserved.</p>
          <p className="font-mono text-xs tracking-wide text-slate-400">
            combustion · industrial AI · training
          </p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
