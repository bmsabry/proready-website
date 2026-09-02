import React, { useState } from 'react';
import { ArrowRight, Calendar, User } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Reveal, PageHero, CTABand } from '../components/ui';
import { usePageMeta } from '../lib/meta';

const FILTERS = ['All', 'Test Infrastructure', 'Emissions & Measurement', 'Fuel Systems', 'Oil & Gas / Process'] as const;
type Filter = (typeof FILTERS)[number];

const caseStudies = [
  {
    id: 14,
    title: "Recovery Reactor Feed Cooler Heat Exchanger",
    excerpt: "Precision thermal design for a critical process stream: a code-compliant TEMA BFU shell and tube heat exchanger in SS TP316L for a chemically aggressive petrochemical environment.",
    category: "Operational Excellence",
    group: "Oil & Gas / Process",
    date: "Mar 17, 2026",
    author: "Mohamed Bakr",
    image: "/Recovery_Reactor_Feed_Cooler_Heat_Exchanger.jpg",
    link: "/case-studies/recovery-reactor-feed-cooler-heat-exchanger"
  },
  {
    id: 13,
    title: "Reinstatement of Polypropylene Plant – High Pressure Blow Down Vessel",
    excerpt: "Emergency fabrication of a 145-metric-ton pressure vessel under tight schedule and complex design constraints for post-explosion plant reinstatement at NATPET Yanbu facility.",
    category: "Pressure Vessel Fabrication",
    group: "Oil & Gas / Process",
    date: "Mar 2, 2026",
    author: "Mohamed Bakr",
    image: "/Reinstatement_of_Polypropylene_Plant_High_Pressure_Blow_Down_Vessel.png",
    link: "/case-studies/reinstatement-of-polypropylene-plant-high-pressure-blow-down-vessel"
  },
  {
    id: 12,
    title: "Fuel Supply Capability Expansion – Specification, Procurement, and Commissioning",
    excerpt: "Enable higher‑flow natural‑gas testing with new capabilities for nitrogen doping and propane blending through complete specification, procurement, and commissioning.",
    category: "Combustion Systems",
    group: "Fuel Systems",
    date: "Feb 20, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/CASE_STUDY_Fuel_Supply_Capability_Expansion__Specification_Procurement_and_Commissioning.jpg",
    link: "/case-studies/case-study-fuel-supply-capability-expansion-specification-procurement-and-commissioning"
  },
  {
    id: 10,
    title: "Protecting Millions: Smart Logic for Combustion Testing Failures",
    excerpt: "High-value combustion test articles (hundreds of thousands of dollars each) were exposed to multiple failure scenarios with potential for catastrophic damage.",
    category: "Safety & Protection Systems",
    group: "Test Infrastructure",
    date: "Feb 17, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/Test_Asset_Protection_Logic.jpg",
    link: "/case-studies/test-asset-protection-logic"
  },
  {
    id: 11,
    title: "New High‑Performance Data Acquisition System",
    excerpt: "From decades-old bottleneck to dynamic, test-engineer-driven tool in 12 weeks. Delivered as MVP in 3 weeks, fully functional in 12 weeks.",
    category: "Data Quality & Throughput",
    group: "Test Infrastructure",
    date: "Feb 17, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/New_HighPerformance_Data_Acquisition_System.jpg",
    link: "/case-studies/new-highperformance-data-acquisition-system"
  },
  {
    id: 9,
    title: "Oil Filtration and Particle Removal in Sensitive Optics Cooling Air",
    excerpt: "Contaminated cooling air was carrying oil and particles onto sensitive optics and into the combustor, risking hardware damage and biased emissions data.",
    category: "Emissions & Instrumentation",
    group: "Emissions & Measurement",
    date: "Feb 16, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case-study-oil-filtration-and-particle-removal-in-sensitive-optics-cooling-air.jpg",
    link: "/case-studies/oil-filtration-and-particle-removal"
  },
  {
    id: 3,
    title: "Optimizing Test Cell Assembly",
    excerpt: "A major engine test facility faced long hardware assembly times that slowed every test campaign. Each program required roughly two weeks of setup before testing could begin, burning schedule and resources.",
    category: "Operational Excellence",
    group: "Test Infrastructure",
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
    group: "Test Infrastructure",
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
    group: "Emissions & Measurement",
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
    group: "Emissions & Measurement",
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
    group: "Fuel Systems",
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
    group: "Fuel Systems",
    date: "Feb 13, 2026",
    author: "Dr. Bassam Abdelnabi",
    image: "/case-study-improving-gaseous-fuel-supply-system-response.jpg",
    link: "/case-studies/improving-gaseous-fuel-supply-system-response"
  }
];

const CaseStudies = () => {
  usePageMeta(
    'Case Studies: Proven Results in Gas Turbine & Thermal-Fluid Engineering',
    'Real projects, measurable outcomes: test infrastructure, emissions measurement, fuel systems, and oil & gas process engineering delivered by ProReadyEngineer.'
  );

  const [filter, setFilter] = useState<Filter>('All');
  const visible = filter === 'All' ? caseStudies : caseStudies.filter((s) => s.group === filter);

  return (
    <div className="pb-0">
      <PageHero
        eyebrow="Proven Results"
        title={<>Case <span className="text-gradient">Studies</span></>}
        subtitle="Real projects, measurable outcomes. How we de-risk test campaigns, harden fuel and emissions systems, and deliver under schedules others call impossible."
      />

      <section className="pb-20 lg:pb-28">
        <div className="container-site">
          {/* Category filter */}
          <Reveal className="flex flex-wrap items-center justify-center gap-3 mb-12" delay={0.05}>
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                aria-pressed={filter === f}
                className={`px-4 py-2 rounded-full text-xs font-mono uppercase tracking-wider border transition-all duration-200 ${
                  filter === f
                    ? 'bg-cyan-500/15 border-cyan-500/40 text-cyan-300 shadow-glow-cyan'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-600 hover:text-slate-200'
                }`}
              >
                {f}
              </button>
            ))}
          </Reveal>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {visible.map((study, i) => (
              <Reveal key={`${filter}-${study.id}`} delay={Math.min(i * 0.06, 0.3)} className="h-full">
                <article className="group card card-hover h-full flex flex-col overflow-hidden">
                  <Link to={study.link} className="block aspect-video overflow-hidden" tabIndex={-1} aria-hidden="true">
                    <img
                      src={study.image}
                      alt={study.title}
                      loading="lazy"
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                    />
                  </Link>
                  <div className="p-7 flex flex-col flex-grow">
                    <div className="flex items-center gap-3 mb-4">
                      <span className="text-[11px] font-mono uppercase tracking-widest text-cyan-400">
                        {study.category}
                      </span>
                      <span className="text-slate-500" aria-hidden="true">/</span>
                      <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
                        <Calendar className="w-3 h-3" aria-hidden="true" />
                        {study.date}
                      </span>
                    </div>

                    <h3 className="text-lg font-bold leading-snug mb-3">
                      <Link to={study.link} className="group-hover:text-cyan-400 transition-colors">
                        {study.title}
                      </Link>
                    </h3>
                    <p className="text-slate-300 text-sm leading-relaxed mb-6 flex-grow">
                      {study.excerpt}
                    </p>

                    <div className="flex items-center justify-between pt-5 border-t border-slate-800/80">
                      <span className="inline-flex items-center gap-2 text-xs text-slate-400">
                        <User className="w-3.5 h-3.5" aria-hidden="true" />
                        {study.author}
                      </span>
                      <Link to={study.link} className="btn-ghost group-hover:gap-3">
                        Read More <ArrowRight className="w-4 h-4" aria-hidden="true" />
                      </Link>
                    </div>
                  </div>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <CTABand
        title="Have a complex engineering challenge?"
        subtitle="Let's discuss how our expertise can help you achieve your goals and drive innovation in your industry."
        primaryLabel="Start a Conversation"
      />
    </div>
  );
};

export default CaseStudies;
