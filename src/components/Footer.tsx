import React from 'react';
import { Link } from 'react-router-dom';
import { Linkedin, Twitter, Mail } from 'lucide-react';

const Footer = () => {
  return (
    <footer className="bg-slate-950 border-t border-slate-900 pt-16 pb-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-12">
          <div className="col-span-1 md:col-span-1">
            <Link to="/" className="flex items-center space-x-3 mb-6">
              <img 
                src="/Logo.jpg" 
                alt="ProReadyEngineer Logo" 
                className="h-8 w-auto rounded-md"
              />
              <span className="text-lg font-bold">ProReadyEngineer</span>
            </Link>
            <p className="text-slate-400 text-sm leading-relaxed">
              Advanced consulting in thermal fluid sciences, gas turbine combustion, and AI-driven engineering solutions.
            </p>
          </div>
          
          <div>
            <h4 className="text-white font-semibold mb-6">Services</h4>
            <ul className="space-y-4 text-sm text-slate-400">
              <li><Link to="/services" className="hover:text-cyan-400 transition-colors">Thermal Fluid Sciences</Link></li>
              <li><Link to="/services" className="hover:text-cyan-400 transition-colors">Gas Turbine Combustion</Link></li>
              <li><Link to="/services" className="hover:text-cyan-400 transition-colors">AI & Data Analytics</Link></li>
              <li><Link to="/training" className="hover:text-cyan-400 transition-colors">Training & Workshops</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="text-white font-semibold mb-6">Company</h4>
            <ul className="space-y-4 text-sm text-slate-400">
              <li><Link to="/case-studies" className="hover:text-cyan-400 transition-colors">Case Studies</Link></li>
              <li><Link to="/insights" className="hover:text-cyan-400 transition-colors">Research Insights</Link></li>
              <li><Link to="/contact" className="hover:text-cyan-400 transition-colors">Contact Us</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="text-white font-semibold mb-6">Connect</h4>
            <div className="flex space-x-4">
              <a href="#" className="p-2 bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors text-slate-400 hover:text-cyan-400">
                <Linkedin className="w-5 h-5" />
              </a>
              <a href="#" className="p-2 bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors text-slate-400 hover:text-cyan-400">
                <Twitter className="w-5 h-5" />
              </a>
              <a href="mailto:info@proreadyengineer.com" className="p-2 bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors text-slate-400 hover:text-cyan-400">
                <Mail className="w-5 h-5" />
              </a>
            </div>
          </div>
        </div>
        
        <div className="border-t border-slate-900 pt-8 flex flex-col md:row justify-between items-center text-xs text-slate-500">
          <p>© 2026 ProReadyEngineer LLC. All rights reserved.</p>
          <div className="flex space-x-6 mt-4 md:mt-0">
            <a href="#" className="hover:text-slate-300">Privacy Policy</a>
            <a href="#" className="hover:text-slate-300">Terms of Service</a>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;