import React from 'react';
import { ArrowRight, Calendar, User } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Reveal, PageHero, CTABand } from '../components/ui';
import { usePageMeta } from '../lib/meta';

const posts = [
  {
    id: 8,
    title: "The Critical Impact of Operational Modes on Gas Turbine Combustor Performance",
    excerpt: "In the pursuit of increased power density and thermal efficiency, liner durability has solidified as the primary technical bottleneck for gas turbine longevity. The mechanical integrity of the combustor hardware is dictated by the synergy between absolute maximum metal temperatures and steep temperature gradients.",
    date: "Mar 5, 2026",
    author: "Dr. Bassam Abdelnabi",
    category: "Technical Analysis",
    image: "/Impact_of_Operational_Modes_on_Gas_Turbine_Combustor_Performance.jpg",
    link: "/insights/operational-modes-impact"
  },
  {
    id: 7,
    title: "Transitioning DLE Combustion Systems to 100% Hydrogen Operation",
    excerpt: "As the global energy landscape pivots toward a hydrogen economy, the aerospace and power generation sectors face a fundamental strategic necessity: redefining the kinetic boundaries of existing gas turbine hardware. Central to this transition is the understanding of laminar flame speed and flashback propensity in hydrogen combustion.",
    date: "Feb 20, 2026",
    author: "Dr. Bassam Abdelnabi",
    category: "Technical Analysis",
    image: "/Hydrogen_Impact_on_Combustor_Performance_and_NOx_Emissions.jpg",
    link: "/insights/transitioning-dle-combustion-systems-to-100-hydrogen"
  },
  {
    id: 6,
    title: "A Technical Deep Dive: Quantifying the Impact of Secondary Air on DLE Combustor Emissions",
    excerpt: "The central challenge in modern Dry Low Emissions (DLE) combustion systems is the continuous drive to reduce Nitric Oxide (NOx) emissions while simultaneously managing critical operational constraints...",
    date: "Jan 28, 2026",
    author: "Dr. Bassam Abdelnabi",
    category: "Technical Analysis",
    image: "/impact-secondary-air-emissions.jpg",
    link: "/insights/secondary-air-impact"
  },
  {
    id: 1,
    title: "Decoding the Vortex: A Technical Deep-Dive into Breakdown Dynamics and Stability",
    excerpt: "In the rigorous analysis of high-speed fluid mechanics, 'vortex breakdown' is defined as a abrupt and drastic change in the structure of a swirling flow. Discover the mechanical thresholds, numerical evolution, and enstrophy intensification associated with this transition.",
    category: "Technical Analysis",
    author: "Dr. Bassam Abdelnabi",
    date: "Jan 25, 2026",
    image: "/Vortex_Break_Down_Image.png",
    link: "/insights/vortex-breakdown"
  },
  {
    id: 2,
    title: "An Experimental Analysis of Combustor Flow Structure Evolution",
    excerpt: "In the design of Gas Turbine Combustors (GTC), aerodynamics—specifically the structure of the internal flow field—plays a critical role in ensuring flame stability and managing pollutant emissions. This study presents an experimental investigation into how modifications to the combustion chamber geometry can be used to control the flow field structure.",
    category: "Technical Analysis",
    author: "Dr. Bassam Abdelnabi",
    date: "Jan 26, 2026",
    image: "/SAC_Flow_Evolution.jpg",
    link: "/insights/combustor-flow-evolution"
  },
  {
    id: 3,
    title: "Single Annular Combustor Automated Design",
    excerpt: "The design of Gas Turbine Combustors (GTC) is an inherently complex and time-intensive process. This technical analysis performs a deep dive into an automated methodology for the preliminary design phase of Fuel Rich Dome Combustors.",
    category: "Technical Analysis",
    author: "Dr. Bassam Abdelnabi",
    date: "Jan 26, 2026",
    image: "/SAC_Design_Infographic.png",
    link: "/insights/automated-combustor-design"
  },
  {
    id: 4,
    title: "Technical Analysis of Combustion Dynamics in Single Annular Combustor (SAC) Sectors",
    excerpt: "Thermo-acoustic instabilities represent a significant obstacle in lean-premixed gas turbine technology. This analysis explores the Rayleigh Criterion and the mechanisms driving pressure pulsations in swirl-stabilized systems.",
    category: "Technical Analysis",
    author: "Dr. Bassam Abdelnabi",
    date: "Jan 26, 2026",
    image: "/SAC_Dynamics.jpg",
    link: "/insights/sac-dynamics"
  },
  {
    id: 5,
    title: "Aerodynamics of a Single Annular Combustor",
    excerpt: "This analysis details the experimental investigation of aerodynamics within a realistic Single Annular Combustor (SAC) sector, also known as a Fuel Rich Dome Combustor. In the design and development of Gas Turbine Combustors (GTC), aerodynamics are of the first priority, playing a vital role in combustion stability, emissions, and overall dynamics.",
    category: "Technical Analysis",
    author: "Dr. Bassam Abdelnabi",
    date: "Jan 26, 2026",
    image: "/SAC_Aerodynamics.jpg",
    link: "/insights/sac-aerodynamics"
  }
];

const Insights = () => {
  usePageMeta(
    'Research Insights: Combustion, Thermal-Fluid & Hydrogen Deep Dives',
    'From the lab to your desk: technical deep dives into gas turbine combustion, DLE emissions, hydrogen transition, vortex dynamics, and combustor design from ProReadyEngineer.'
  );

  return (
    <div className="pb-0">
      <PageHero
        eyebrow="Research Insights"
        title={<>From the <span className="text-gradient">Lab</span></>}
        subtitle="Deep dives into thermal-fluid sciences, combustion research, and the application of AI in modern engineering, written by the engineers doing the work."
      />

      <section className="pb-20 lg:pb-28">
        <div className="container-site">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {posts.map((post, i) => (
              <Reveal key={post.id} delay={Math.min(i * 0.06, 0.3)} className="h-full">
                <article className="group card card-hover h-full flex flex-col overflow-hidden">
                  <Link to={post.link} className="block aspect-video overflow-hidden" tabIndex={-1} aria-hidden="true">
                    <img
                      src={post.image}
                      alt={post.title}
                      loading="lazy"
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                    />
                  </Link>
                  <div className="p-7 flex flex-col flex-grow">
                    <div className="flex items-center gap-3 mb-4">
                      <span className="text-[11px] font-mono uppercase tracking-widest text-cyan-400">
                        {post.category}
                      </span>
                      <span className="text-slate-500" aria-hidden="true">/</span>
                      <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
                        <Calendar className="w-3 h-3" aria-hidden="true" />
                        {post.date}
                      </span>
                    </div>

                    <h3 className="text-lg font-bold leading-snug mb-3">
                      <Link to={post.link} className="group-hover:text-cyan-400 transition-colors">
                        {post.title}
                      </Link>
                    </h3>
                    <p className="text-slate-300 text-sm leading-relaxed mb-6 flex-grow">
                      {post.excerpt}
                    </p>

                    <div className="flex items-center justify-between pt-5 border-t border-slate-800/80">
                      <span className="inline-flex items-center gap-2 text-xs text-slate-400">
                        <User className="w-3.5 h-3.5" aria-hidden="true" />
                        {post.author}
                      </span>
                      <Link to={post.link} className="btn-ghost group-hover:gap-3">
                        Read More <ArrowRight className="w-4 h-4" aria-hidden="true" />
                      </Link>
                    </div>
                  </div>
                </article>
              </Reveal>
            ))}
          </div>

          {/* Newsletter */}
          <Reveal className="mt-16">
            <div className="card p-8 md:p-12 flex flex-col md:flex-row items-center justify-between gap-8">
              <div className="max-w-md">
                <h2 className="text-2xl font-bold mb-2">Stay Updated</h2>
                <p className="text-slate-300 text-sm">
                  Get our latest technical papers and case studies delivered directly to your inbox.
                </p>
              </div>
              <div className="flex w-full md:w-auto gap-3">
                <label htmlFor="newsletter-email" className="sr-only">Email address for newsletter</label>
                <input
                  id="newsletter-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  placeholder="engineering@company.com"
                  className="flex-grow md:w-64 bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors"
                />
                <button className="btn-primary whitespace-nowrap">Subscribe</button>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      <CTABand
        title="Want this expertise on your problem?"
        subtitle="The same rigor behind these analyses goes into every client engagement, from combustion test campaigns to hydrogen readiness studies."
        primaryLabel="Consult with Experts"
        secondaryLabel="See Proven Results"
        secondaryTo="/case-studies"
      />
    </div>
  );
};

export default Insights;
