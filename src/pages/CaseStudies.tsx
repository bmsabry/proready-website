import React from 'react';
import { motion } from 'framer-motion';
import { Briefcase, ArrowRight, Calendar, User, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

const caseStudies = [
  {
    id: 10,
    title: "Protecting Millions: Smart Logic for Combustion Testing Failures",
    excerpt: "High-value combustion test articles (hundreds of thousands of dollars each) were exposed to multiple failure scenarios with potential for catastrophic damage.",
    category: "Safety & Protection Systems",
    date: "Feb 17, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/Test_Asset_Protection_Logic.jpg",
    link: "/case-studies/test-asset-protection-logic"
  },
  {
    id: 9,
    title: "Oil Filtration and Particle Removal in Sensitive Optics Cooling Air",
    excerpt: "Contaminated cooling air was carrying oil and particles onto sensitive optics and into the combustor, risking hardware damage and biased emissions data.",
    category: "Emissions & Instrumentation",
    date: "Feb 16, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case-study-oil-filtration-and-particle-removal-in-sensitive-optics-cooling-air.jpg",
    link: "/case-studies/oil-filtration-and-particle-removal"
  },
  {
    id: 3,
    title: "Optimizing Test Cell Assembly",
    excerpt: "A major engine test facility faced long hardware assembly times that slowed every test campaign. Each program required roughly two weeks of setup before testing could begin—burning valuable schedule and resources.",
    category: "Operational Excellence",
    date: "Feb 05, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/optimizing-test-cell-assembly.png",
    link: "/case-studies/optimizing-test-cell-assembly"
  },
  {
    id: 4,
    title: "Enhancing Test Execution Cost & Efficiency",
    excerpt: "Manual test operations led to limited data capture, post‑processing delays, and repeat testing. A major aerospace test organization achieved a 40% increase in daily data points and 50% staffing reduction per test.",
    category: "Data Quality & Throughput",
    date: "Feb 10, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case2-study-enhancing-test-execution-cost-efficiency.jpg",
    link: "/case-studies/enhancing-test-execution-cost-efficiency"
  },
  {
    id: 5,
    title: "Innovative system that enables multichannel emissions sampling",
    excerpt: "Delivering a faster, simpler, and 62% cheaper solution in eight weeks for a major combustion test facility needing a multichannel emissions sampling system.",
    category: "Emissions & Instrumentation",
    date: "Feb 11, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case-study-enabling-multichannel-emissions-sampling.jpg",
    link: "/case-studies/multichannel-emissions-sampling"
  },
  {
    id: 6,
    title: "Extending Emissions Probe Durability",
    excerpt: "Redesigning probe cooling and structural support systems to withstand extreme thermal gradients and aerodynamic loads in high-temperature exhaust streams.",
    category: "Emissions & Instrumentation",
    date: "Feb 13, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case-study-extending-emissions-rake-durability.jpg",
    link: "/case-studies/extending-emissions-probe-durability"
  },
  {
    id: 7,
    title: "Specifying, Procuring, and Installing a Dual‑Mode Liquid‑Fuel Pumping System",
    excerpt: "Delivering a high‑pressure liquid‑fuel pumping system capable of both dry‑fuel and fuel‑water emulsion operation with advanced control and redundancy.",
    category: "Combustion Systems",
    date: "Feb 13, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case-study-specifying-procuring-and-installing-a-dualmode-liquidfuel-pumping-system.jpg",
    link: "/case-studies/dual-mode-liquid-fuel-pumping-system"
  },
  {
    id: 8,
    title: "Improving Gaseous Fuel Supply System Response",
    excerpt: "Ten electronically actuated control valves replaced the pneumatic set, improving flow‑adjustment response by ≈ 35 %, introducing auto‑calibration and durable trim materials, and enhancing overall system readiness.",
    category: "Combustion Systems",
    date: "Feb 13, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case-study-improving-gaseous-fuel-supply-system-response.jpg",
    link: "/case-studies/improving-gaseous-fuel-supply-system-response"
  }
];

const CaseStudies = () => {
  return (
    <div className="pt-32 pb-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mb-16">
          <h1 className="text-4xl md:text-5xl font-bold mb-6">Case <span className="text-gradient">Studies</span></h1>
          <p className="text-slate-400 text-lg">
            Real-world applications of our engineering expertise and the measurable impact we've delivered for our clients.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {caseStudies.map((study, i) => (
            <motion.article
              key={study.id}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
              className="group flex flex-col bg-slate-900/50 border border-slate-800 rounded-3xl overflow-hidden hover:border-slate-700 transition-all"
            >
              <Link to={study.link} className="aspect-video overflow-hidden">
                <img 
                  src={study.image} 
                  alt={study.title} 
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                />
              </Link>
              <div className="p-8 flex flex-col flex-grow">
                <div className="flex items-center gap-4 mb-4">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-cyan-400 uppercase tracking-wider">
                    <Tag className="w-3 h-3" />
                    {study.category}
                  </span>
                  <span className="text-slate-600">•</span>
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    <Calendar className="w-3 h-3" />
                    {study.date}
                  </span>
                </div>
                
                <Link to={study.link}>
                  <h3 className="text-xl font-bold mb-4 group-hover:text-cyan-400 transition-colors leading-tight">
                    {study.title}
                  </h3>
                </Link>
                <p className="text-slate-400 text-sm mb-8 flex-grow leading-relaxed">
                  {study.excerpt}
                </p>

                <div className="flex items-center justify-between pt-6 border-t border-slate-800">
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-slate-800 flex items-center justify-center">
                      <User className="w-3 h-3 text-slate-400" />
                    </div>
                    <span className="text-xs text-slate-400">{study.author}</span>
                  </div>
                  <Link to={study.link} className="text-cyan-400 text-sm font-medium flex items-center gap-1 hover:gap-2 transition-all">
                    Read More <ArrowRight className="w-4 h-4" />
                  </Link>
                </div>
              </div>
            </motion.article>
          ))}
        </div>

        {/* Contact CTA */}
        <div className="mt-24 p-12 rounded-[3rem] bg-gradient-to-br from-slate-900 to-slate-950 border border-slate-800 text-center">
          <h2 className="text-3xl font-bold mb-4">Have a complex engineering challenge?</h2>
          <p className="text-slate-400 mb-8 max-w-2xl mx-auto">
            Let's discuss how our expertise can help you achieve your goals and drive innovation in your industry.
          </p>
          <Link to="/contact" className="btn-primary inline-flex px-8 py-4">
            Start a Conversation
          </Link>
        </div>
      </div>
    </div>
  );
};

export default CaseStudies;
