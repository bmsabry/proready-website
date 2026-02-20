import React from 'react';
import { motion } from 'framer-motion';
import { Calendar, User, ArrowRight, Tag } from 'lucide-react';
import { Link } from 'react-router-dom';

const posts = [
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
  return (
    <div className="pt-32 pb-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mb-16">
          <h1 className="text-4xl md:text-5xl font-bold mb-6">Research <span className="text-gradient">Insights</span></h1>
          <p className="text-slate-400 text-lg">
            Deep dives into thermal fluid sciences, combustion research, and the application of AI in modern engineering.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {posts.map((post, i) => (
            <motion.article
              key={post.id}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
              className="group flex flex-col bg-slate-900/50 border border-slate-800 rounded-3xl overflow-hidden hover:border-slate-700 transition-all"
            >
              <Link to={post.link} className="aspect-video overflow-hidden">
                <img 
                  src={post.image} 
                  alt={post.title} 
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                />
              </Link>
              <div className="p-8 flex flex-col flex-grow">
                <div className="flex items-center gap-4 mb-4">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-cyan-400 uppercase tracking-wider">
                    <Tag className="w-3 h-3" />
                    {post.category}
                  </span>
                  <span className="text-slate-600">•</span>
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    <Calendar className="w-3 h-3" />
                    {post.date}
                  </span>
                </div>
                
                <Link to={post.link}>
                  <h3 className="text-xl font-bold mb-4 group-hover:text-cyan-400 transition-colors leading-tight">
                    {post.title}
                  </h3>
                </Link>
                <p className="text-slate-400 text-sm mb-8 flex-grow leading-relaxed">
                  {post.excerpt}
                </p>

                <div className="flex items-center justify-between pt-6 border-t border-slate-800">
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-slate-800 flex items-center justify-center">
                      <User className="w-3 h-3 text-slate-400" />
                    </div>
                    <span className="text-xs text-slate-400">{post.author}</span>
                  </div>
                  <Link to={post.link} className="text-cyan-400 text-sm font-medium flex items-center gap-1 hover:gap-2 transition-all">
                    Read More <ArrowRight className="w-4 h-4" />
                  </Link>
                </div>
              </div>
            </motion.article>
          ))}
        </div>

        {/* Newsletter CTA */}
        <div className="mt-24 p-12 rounded-[3rem] bg-slate-900 border border-slate-800 flex flex-col md:flex-row items-center justify-between gap-8">
          <div className="max-w-md">
            <h2 className="text-2xl font-bold mb-2">Stay Updated</h2>
            <p className="text-slate-400 text-sm">
              Get our latest technical papers and case studies delivered directly to your inbox.
            </p>
          </div>
          <div className="flex w-full md:w-auto gap-3">
            <input 
              type="email" 
              placeholder="engineering@company.com" 
              className="flex-grow md:w-64 bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-500 transition-colors"
            />
            <button className="btn-primary whitespace-nowrap">Subscribe</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Insights;