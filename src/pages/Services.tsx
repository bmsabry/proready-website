import React from 'react';
import { motion } from 'framer-motion';
import { Flame, Brain, GraduationCap, CheckCircle2, Zap, BarChart3, Microscope } from 'lucide-react';

const ServiceCard = ({ title, icon, description, features, color }: any) => (
  <motion.div 
    initial={{ opacity: 0, y: 20 }}
    whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true }}
    className="p-8 rounded-3xl bg-slate-900/50 border border-slate-800 hover:border-slate-700 transition-all"
  >
    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center mb-6 bg-slate-950 border border-slate-800`}>
      {React.cloneElement(icon, { className: `w-7 h-7 ${color}` })}
    </div>
    <h3 className="text-2xl font-bold mb-4">{title}</h3>
    <p className="text-slate-400 mb-8 leading-relaxed">
      {description}
    </p>
    <ul className="space-y-4">
      {features.map((feature: string, i: number) => (
        <li key={i} className="flex items-start gap-3 text-sm text-slate-300">
          <CheckCircle2 className={`w-5 h-5 shrink-0 ${color}`} />
          {feature}
        </li>
      ))}
    </ul>
  </motion.div>
);

const Services = () => {
  const services = [
    {
      title: "Thermal Fluid Sciences",
      icon: <Flame />,
      color: "text-orange-500",
      description: "Expert consulting in high-temperature fluid dynamics and combustion systems, with a focus on gas turbine efficiency and emissions.",
      features: [
        "Gas Turbine Combustion emissions optimization",
        "Experimental Design & Data Interpretation",
        "Emissions Reduction Technologies",
        "Test Facility design, specification and sizing",
        "Computational Fluid Dynamics (CFD) Analysis",
        "Test Execution Automation including Auto-mapping"
      ]
    },
    {
      title: "AI & Data Analytics",
      icon: <Brain />,
      color: "text-cyan-500",
      description: "Bridging the gap between physics-based engineering and modern machine learning to unlock hidden insights in your data.",
      features: [
        "Predictive Maintenance Models",
        "Neural Networks",
        "Digital Twin Development",
        "Automated Data Processing Pipelines",
        "Anomaly Detection in Sensor Data"
      ]
    },
    {
      title: "Training & Workshops",
      icon: <GraduationCap />,
      color: "text-blue-500",
      description: "Empowering engineering teams with the latest tools and methodologies through hands-on technical training.",
      features: [
        "Advanced Combustion Fundamentals",
        "Gas Turbine Combustion",
        "Fundamentals of Turbomachinery",
        "Data Visualization & Advanced Analytics",
        "Applied Machine Learning & AI for Engineers",
        "CFD Best Practices & Simulation",
        "Custom Corporate Training Programs"
      ]
    }
  ];

  return (
    <div className="pt-32 pb-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto mb-20">
          <motion.h1 
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-4xl md:text-5xl font-bold mb-6"
          >
            Specialized <span className="text-gradient">Engineering Services</span>
          </motion.h1>
          <p className="text-slate-400 text-lg">
            We combine deep domain expertise in thermal sciences with advanced computational 
            capabilities to solve the most complex engineering challenges.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-32">
          {services.map((s, i) => (
            <ServiceCard key={i} {...s} />
          ))}
        </div>

        {/* Methodology Section */}
        <div className="rounded-[3rem] bg-gradient-to-b from-slate-900 to-slate-950 border border-slate-800 p-8 md:p-16">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
            <div>
              <h2 className="text-3xl font-bold mb-8">Our Approach: <br /><span className="text-cyan-400">Physics-First AI</span></h2>
              <p className="text-slate-400 mb-8 leading-relaxed">
                Unlike generic data science firms, we understand the underlying physics of your systems. 
                Our "Physics-First" approach ensures that AI models are not just accurate, but physically 
                consistent and explainable.
              </p>
              <div className="space-y-6">
                {[
                  { icon: <Microscope />, title: "Deep Domain Knowledge", desc: "Decades of experience in gas turbine and thermal systems." },
                  { icon: <Zap />, title: "Rapid Prototyping", desc: "Quickly validate ideas with high-fidelity simulations." },
                  { icon: <BarChart3 />, title: "Actionable Insights", desc: "We don't just provide data; we provide engineering solutions." }
                ].map((item, i) => (
                  <div key={i} className="flex gap-4">
                    <div className="p-2 bg-slate-800 rounded-lg h-fit text-cyan-400">
                      {item.icon}
                    </div>
                    <div>
                      <h4 className="font-semibold text-white">{item.title}</h4>
                      <p className="text-sm text-slate-500">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="relative">
              <div className="aspect-square rounded-2xl bg-slate-800/50 border border-slate-700 flex items-center justify-center overflow-hidden">
                {/* Placeholder for a technical illustration/animation */}
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-cyan-500/10 via-transparent to-transparent"></div>
                <div className="text-center p-8">
                  <div className="w-24 h-24 bg-cyan-500/20 rounded-full blur-2xl absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2"></div>
                  <Brain className="w-20 h-20 text-cyan-500 relative z-10 mx-auto mb-4 animate-pulse" />
                  <p className="text-xs font-mono text-cyan-400/60 uppercase tracking-widest">Neural Network Analysis</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Services;