import React from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, Flame, Brain, GraduationCap, Linkedin, Mail } from 'lucide-react';
import { Link } from 'react-router-dom';

const Home = () => {
  const team = [
    {
      name: "Dr. Bassam Abdelnabi",
      role: "Principal Consultant, Gas Turbine Combustion Expert",
      bio: "Dr. Bassam Abdelnabi is a Gas Turbine Combustion Expert who operates at the intersection of thermal fluid sciences, advanced data analytics, and high-pressure experimental infrastructure. He holds a Ph.D. in Aerospace Engineering and has led advanced R&D, combustion system design, and automated testing initiatives across the aviation and power generation sectors, including over a decade of leadership at GE Aerospace and GE Global Research. His infrastructure expertise encompasses the end-to-end design, specification, and construction of high-pressure industrial test cells, complete with the required auxiliary air, fuel, quench, measurement, and control systems. Beyond design and testing, he leverages Digital Twin modeling and field mapping expertise to execute precise gas turbine emissions optimization. Bassam also possesses extensive experience with a wide range of gaseous fuels, including hydrogen and liquid fuels including crude oil. Known for his \"Don't Take No for an Answer\" approach to resolving technical crises previously declared \"unsolvable,\" he helps organizations develop, design, validate, and deploy next-generation combustion systems that ensure regulatory compliance.",
      image: "/Bassam.jpg"
    },
    {
      name: "John Battaglioli",
      role: "CFD & Thermal-Fluid Systems Expert",
      bio: "John is a distinguished authority in Computational Fluid Dynamics (CFD) and thermal-fluid systems with 45 years of leadership across the Power and Aerospace sectors. His career is defined by a rare ability to bridge the gap between complex software development and the deployment of robust, fielded hardware. A pioneer in low-emissions technology, John holds numerous patents in Dry Low NOx (DLN) combustion, achieving industry-leading single-digit NOx and CO performance. Beyond his technical contributions to nuclear, wind, and carbon capture systems, he has commanded global manufacturing and field service organizations, ensuring that cutting-edge innovation meets the rigors of industrial operations.",
      image: "/John.jpg"
    },
    {
      name: "Dr. Ammar Abdilghanie",
      role: "Industrial AI Expert",
      bio: "Ammar Abdilghanie is an Industrial AI expert who operates at the intersection of engineering, data science, and real-world industrial systems. He holds a PhD in mechanical engineering and has led advanced analytics, automation, and AI initiatives across aerospace, energy, and manufacturing, including work at Blue Origin as well as oil and gas and energy technology companies such as Baker Hughes and Halliburton. Ammar has applied Computer vision, Bayesian statistics, Machine learning and Generative AI to solve complex industrial problems, with a focus on inspection and testing systems automation, maintenance, and reliability engineering, and on building scalable, production-grade industrial data and decision systems. Known for bridging deep technical rigor with practical execution, he helps organizations move beyond prototypes to deploy Industrial AI solutions that deliver measurable operational impact in Industry 4.0 environments.",
      image: "/Ammar.jpg"
    },
    {
      name: "Dr. Zaeem Khan",
      role: "FEA & Structural Analysis Specialist",
      bio: "Dr. Zaeem Khan is a specialist in high-fidelity thermal and structural Finite Element Analysis (FEA), dedicated to helping engineering firms and startups navigate the complexities of product development. With a career spanning the automotive industry, R&D at the GE Global Research Center, and the successful leadership of an NSF-funded startup, Dr. Khan brings a unique, holistic perspective to every project. He goes beyond the numbers to consider the variables that truly dictate a product's success: material cost, manufacturing feasibility, and long-term durability. By developing custom tools and macros, Dr. Khan delivers rapid, error-free analysis grounded in the latest analytical methods. Whether you are validating a new concept or diagnosing a failure in an existing design, he provides the data-driven clarity needed to reduce time-to-market and ensure structural integrity.",
      image: "/Zaeem.jpg"
    },
    {
      name: "Adam Bailey",
      role: "Senior Mechanical Designer",
      bio: "Adam Bailey is a seasoned Mechanical Designer with over 30 years of experience, specializing in the design and development of gas turbine combustion systems. With a deep technical background in GE frames 6B, 7EA, 9E, 7FA, and 9FA, Adam has led the design of numerous complex combustion test rigs. He uniquely bridges the gap between advanced engineering and practical production, leveraging a decade of expertise in additive manufacturing and a robust understanding of DFM (Design for Manufacturability) to optimize system performance and cost.",
      image: "/Adam.jpg"
    }
  ];

  return (
    <div className="pt-20">
      {/* Hero Section */}
      <section className="relative py-20 lg:py-32 overflow-hidden">
        {/* Banner Background */}
        <div className="absolute inset-0 -z-10">
          <img 
            src="/Banner.png" 
            alt="" 
            className="w-full h-full object-cover opacity-20"
          />
          <div className="absolute inset-0 bg-gradient-to-b from-slate-950/80 via-slate-950/60 to-slate-950"></div>
        </div>
        
        {/* Glow Effects */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full h-full -z-10 pointer-events-none">
          <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-cyan-500/10 blur-[120px] rounded-full"></div>
          <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-blue-500/10 blur-[120px] rounded-full"></div>
        </div>

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <span className="inline-block py-1 px-3 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-medium mb-6">
              Engineering the Future of Energy
            </span>
            <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-8">
              Advanced <span className="text-gradient">Thermal Fluid</span> <br />
              & AI Solutions
            </h1>
            <p className="text-lg md:text-xl text-slate-400 max-w-3xl mx-auto mb-6 leading-relaxed">
              ProReadyEngineer LLC provides expert consulting in gas turbine combustion, mechanical power systems,
              advanced data analytics, and specialized technical training for engineers.
            </p>
            <div className="flex flex-col gap-2 mb-10 text-sm font-medium tracking-wide">
              <p className="text-cyan-400/90">
                SAM.GOV Small Business | CAGE: 18X84 | UEI: RLHYXFN7JJN5
              </p>
              <p className="text-slate-500 max-w-2xl mx-auto text-xs uppercase tracking-widest leading-relaxed">
                NAICS CODES: 541330: Primary - Engineering Services <span className="mx-2 text-slate-700">•</span> 
                611430: Professional and Management Development Training <span className="mx-2 text-slate-700">•</span> 
                541611: Consulting Services
              </p>
            </div>
            <div className="flex flex-col sm:flex-row justify-center gap-4">
              <Link to="/contact" className="btn-primary flex items-center justify-center gap-2">
                Consult with Experts <ArrowRight className="w-4 h-4" />
              </Link>
              <Link to="/services" className="btn-secondary">
                Explore Services
              </Link>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Quick Services Grid */}
      <section className="py-20 bg-slate-900/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              {
                title: "Thermal Fluid Sciences",
                desc: "Specialized consulting in gas turbine combustion and heat transfer applications.",
                icon: <Flame className="w-8 h-8 text-orange-500" />,
                link: "/services"
              },
              {
                title: "AI & Data Analytics",
                desc: "Leveraging machine learning and advanced analytics for engineering optimization.",
                icon: <Brain className="w-8 h-8 text-cyan-500" />,
                link: "/services"
              },
              {
                title: "Training & Workshops",
                desc: "Professional development courses in combustion, CFD, and data science.",
                icon: <GraduationCap className="w-8 h-8 text-blue-500" />,
                link: "/training"
              }
            ].map((service, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                className="p-8 rounded-2xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition-all group"
              >
                <div className="mb-6 p-3 bg-slate-950 rounded-xl w-fit group-hover:scale-110 transition-transform">
                  {service.icon}
                </div>
                <h3 className="text-xl font-bold mb-4">{service.title}</h3>
                <p className="text-slate-400 text-sm leading-relaxed mb-6">
                  {service.desc}
                </p>
                <Link to={service.link} className="text-cyan-400 text-sm font-medium flex items-center gap-2 hover:gap-3 transition-all">
                  Learn more <ArrowRight className="w-4 h-4" />
                </Link>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Team Section */}
      <section className="py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">Meet the <span className="text-gradient">Experts</span></h2>
            <p className="text-slate-400 max-w-2xl mx-auto">
              Our team brings together deep academic knowledge and industrial experience to solve your toughest engineering problems.
            </p>
          </div>
          
          <div className="flex flex-col gap-8 max-w-4xl mx-auto">
            {team.map((member, i) => (
              <motion.div 
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                className="flex flex-col md:flex-row gap-6 items-center md:items-start p-6 rounded-3xl bg-slate-900/50 border border-slate-800"
              >
                <img 
                  src={member.image} 
                  alt={member.name} 
                  className="w-24 h-24 rounded-2xl object-cover border-2 border-slate-800"
                />
                <div>
                  <h3 className="text-xl font-bold mb-1">{member.name}</h3>
                  <p className="text-cyan-400 text-sm font-medium mb-3">{member.role}</p>
                  <p className="text-slate-400 text-sm leading-relaxed mb-4">{member.bio}</p>

                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
};

export default Home;