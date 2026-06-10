import React, { useState } from 'react';
import {
  ArrowRight,
  Atom,
  Brain,
  Flame,
  GraduationCap,
  ShieldCheck,
  Target,
  Wrench,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Reveal, SectionHeading, StatCounter, CTABand } from '../components/ui';
import { usePageMeta } from '../lib/meta';

/* ---------------- Data ---------------- */

type TeamMember = {
  name: string;
  role: string;
  bio: string;
  image: string;
};

const team: TeamMember[] = [
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
    name: "Mohamed Bakr",
    role: "Static Equipment & Pressure Vessel Design Expert",
    bio: `Mohamed Bakr is a Senior Engineering Manager and a recognized authority in Static Equipment and Pressure Vessel Design. With over 20 years of experience, he specializes in the detailed design of piping systems and static equipment for complex Oil & Gas projects. Mohamed brings comprehensive expertise across the entire project lifecycle—from initial concept and advanced 2D/3D modeling through detailed engineering, material take-off, and final commissioning.

He is highly skilled in performing rigorous design calculations for pressure vessels and heat exchangers in strict accordance with ASME Section VIII (Div. 1 & Div. 2), API 660, and TEMA standards, utilizing industry-leading software such as Compress, PV Elite, and AutoCAD. Furthermore, his profound understanding of material specifications enables the precise preparation of Material Technical Delivery Conditions (MTDC) that align with ASME Section II and rigorous project specifications. By consistently securing ASME Inspector acceptance for U-stamped pressure vessels, Mohamed ensures the delivery of safe, fully compliant, and exceptionally engineered solutions tailored to the most demanding industrial environments.`,
    image: "/Bakr.png"
  },
  {
    name: "Sherif Ahmed",
    role: "Aerospace Propulsion & Multiphysics Expert",
    bio: `Sherif is an Aerospace Propulsion and Multiphysics Expert who expands our capabilities into high-performance defense aviation, advanced computational thermal management, and biomechanical engineering. Within the aerospace sector, he specializes in whole-engine thermodynamic cycle modeling—having developed high-fidelity models for the F100-PW-229 afterburning turbofan to optimize nozzle control logic and ensure extreme-condition stall protection—alongside pioneering research in hypersonic fuel injection. He also brings deep component-level expertise in Conjugate Heat Transfer (CHT), designing complex internal cooling channels for gas turbine blades as well as innovative liquid-cooling architectures for high-performance computing (GPUs). Beyond traditional power and propulsion, Sherif leverages advanced Fluid-Structure Interaction (FSI) to drive MedTech innovation, most notably leading the advanced CFD/FSI design of a Nitinol aortic stent that improved renal perfusion by 19% and won the prestigious "Best Innovation in the Arab World" award from the Qatar Foundation.`,
    image: "/Sherif.jpg"
  },
  {
    name: "Adam Bailey",
    role: "Senior Mechanical Designer",
    bio: "Adam Bailey is a seasoned Mechanical Designer with over 30 years of experience, specializing in the design and development of gas turbine combustion systems. With a deep technical background in GE frames 6B, 7EA, 9E, 7FA, and 9FA, Adam has led the design of numerous complex combustion test rigs. He uniquely bridges the gap between advanced engineering and practical production, leveraging a decade of expertise in additive manufacturing and a robust understanding of DFM (Design for Manufacturability) to optimize system performance and cost.",
    image: "/Adam.jpg"
  }
];

const pillars = [
  {
    title: "Thermal Fluid Sciences",
    desc: "Gas turbine combustion, heat transfer, and high-pressure test infrastructure, engineered from first principles through commissioning.",
    icon: <Flame className="w-8 h-8 text-orange-500" aria-hidden="true" />,
    link: "/services",
  },
  {
    title: "Industrial AI & Data Analytics",
    desc: "Physics-grounded machine learning and analytics that turn test and field data into faster decisions and measurable operational impact.",
    icon: <Brain className="w-8 h-8 text-cyan-500" aria-hidden="true" />,
    link: "/services",
  },
  {
    title: "Training & Workshops",
    desc: "Courses in combustion, emissions mapping, CFD, and data science, built by practitioners who have done the work themselves.",
    icon: <GraduationCap className="w-8 h-8 text-blue-500" aria-hidden="true" />,
    link: "/training",
  },
];

const differentiators = [
  {
    title: "Physics-First AI",
    desc: "PhD-level domain physics paired with production-grade machine learning. No black boxes: models you can interrogate and deploy.",
    icon: <Atom className="w-6 h-6 text-cyan-400" aria-hidden="true" />,
  },
  {
    title: "Test Cell to Field",
    desc: "We design, build, and commission the hardware we model. End-to-end ownership, from test cell specification to fielded combustion systems.",
    icon: <Wrench className="w-6 h-6 text-cyan-400" aria-hidden="true" />,
  },
  {
    title: "“Don't Take No for an Answer”",
    desc: "A track record of resolving technical crises previously declared unsolvable, under schedule pressure and at full operating conditions.",
    icon: <Target className="w-6 h-6 text-cyan-400" aria-hidden="true" />,
  },
  {
    title: "Compliance-Ready",
    desc: "Emissions regulatory compliance and ASME-stamped pressure vessel work, delivered to inspector acceptance the first time.",
    icon: <ShieldCheck className="w-6 h-6 text-cyan-400" aria-hidden="true" />,
  },
];

const featuredWork = [
  {
    title: "Test Asset Protection Logic",
    outcome: "Smart protection logic shielding six-figure combustion test articles from catastrophic failure scenarios.",
    link: "/case-studies/test-asset-protection-logic",
  },
  {
    title: "Multichannel Emissions Sampling",
    outcome: "A faster, simpler multichannel sampling system delivered in eight weeks at 62% lower cost.",
    link: "/case-studies/multichannel-emissions-sampling",
  },
  {
    title: "Oil Filtration & Particle Removal",
    outcome: "Eliminated oil and particle contamination that threatened sensitive optics and biased emissions data.",
    link: "/case-studies/oil-filtration-and-particle-removal",
  },
];

/* ---------------- Team card with expandable bio ---------------- */

const clampStyle: React.CSSProperties = {
  display: '-webkit-box',
  WebkitLineClamp: 3,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
};

const TeamCard = ({ member, index }: { member: TeamMember; index: number }) => {
  const [expanded, setExpanded] = useState(false);
  const bioId = `bio-${member.name.toLowerCase().replace(/[^a-z]+/g, '-')}`;

  return (
    <Reveal delay={(index % 2) * 0.08} className="h-full">
      <article className="card card-hover h-full flex flex-col p-6 md:p-8">
        <div className="flex items-center gap-5">
          <img
            src={member.image}
            alt={`Portrait of ${member.name}`}
            loading="lazy"
            decoding="async"
            className="w-28 h-28 rounded-2xl object-cover border border-slate-800 shrink-0"
          />
          <div>
            <h3 className="text-lg md:text-xl font-bold leading-snug">{member.name}</h3>
            <p className="text-cyan-400 text-sm font-medium mt-1.5">{member.role}</p>
          </div>
        </div>
        <p
          id={bioId}
          className="text-slate-300 text-sm leading-relaxed mt-5 whitespace-pre-line"
          style={expanded ? undefined : clampStyle}
        >
          {member.bio}
        </p>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={bioId}
          className="btn-ghost mt-3 self-start"
        >
          {expanded ? 'Show less' : 'Read full bio'}
          <ArrowRight
            className={`w-4 h-4 transition-transform ${expanded ? '-rotate-90' : 'rotate-90'}`}
            aria-hidden="true"
          />
        </button>
      </article>
    </Reveal>
  );
};

/* ---------------- Page ---------------- */

const Home = () => {
  usePageMeta(
    'Gas Turbine Combustion & Industrial AI Consulting',
    'ProReadyEngineer LLC: expert consulting in gas turbine combustion, thermal fluid sciences, high-pressure test infrastructure, emissions compliance, and physics-first industrial AI. Ex-GE, PhD-led team. SAM.gov registered small business.'
  );

  return (
    <div>
      {/* ---------- Hero ---------- */}
      <section className="relative flex items-center min-h-[92vh] pt-32 pb-20 overflow-hidden">
        <div className="hero-backdrop" />
        <div className="absolute inset-0 -z-20 bg-hero-radial" />
        <div className="absolute inset-0 -z-30" aria-hidden="true">
          <img
            src="/Banner.png"
            alt=""
            decoding="async"
            className="w-full h-full object-cover opacity-[0.15]"
          />
          <div className="absolute inset-0 bg-gradient-to-b from-slate-950/80 via-slate-950/70 to-slate-950" />
        </div>
        <div className="absolute inset-0 -z-10 pointer-events-none" aria-hidden="true">
          <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-cyan-500/10 blur-[120px] rounded-full" />
          <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-blue-500/10 blur-[120px] rounded-full" />
        </div>
        <div className="container-site text-center">
          <div className="anim-enter">
            <span className="eyebrow mb-6">Combustion &middot; Test Infrastructure &middot; Industrial AI</span>
            <h1 className="text-5xl md:text-6xl lg:text-7xl font-bold tracking-tight mt-6 mb-8 max-w-5xl mx-auto">
              <span className="text-gradient">Thermal Fluid</span> &amp; AI Engineering
              <br className="hidden md:block" /> for Problems Declared Unsolvable
            </h1>
            <p className="text-lg md:text-xl text-slate-300 max-w-3xl mx-auto mb-10 leading-relaxed">
              ProReadyEngineer LLC provides expert consulting in gas turbine combustion, mechanical
              power systems, advanced data analytics, and specialized technical training for engineers.
            </p>
            <div className="flex flex-col sm:flex-row justify-center gap-4">
              <Link to="/contact" className="btn-primary">
                Consult with Experts <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </Link>
              <Link to="/services" className="btn-secondary">
                Explore Services
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- Federal credentials strip ---------- */}
      <section className="border-y border-slate-800/60 bg-slate-900/20">
        <div className="container-site py-4">
          <p className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 font-mono text-xs tracking-wider text-slate-300 text-center">
            <span>SAM.gov Small Business</span>
            <span className="text-slate-500" aria-hidden="true">|</span>
            <span>CAGE 18X84</span>
            <span className="text-slate-500" aria-hidden="true">|</span>
            <span>UEI RLHYXFN7JJN5</span>
            <span className="text-slate-500" aria-hidden="true">|</span>
            <span>NAICS 541330 / 611430 / 541611</span>
          </p>
        </div>
      </section>

      {/* ---------- Stats band ---------- */}
      <section className="py-16 lg:py-20">
        <div className="container-site">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-10">
            <StatCounter value={100} suffix="+" label="Years Combined Experience" />
            <StatCounter value={12} suffix="+" label="Sample Case Studies" />
            <StatCounter value={31} label="Expert Testimonials" />
            <StatCounter value={7} label="Senior Experts" />
          </div>
        </div>
      </section>

      {/* ---------- Three pillars ---------- */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site">
          <SectionHeading
            eyebrow="What We Do"
            title="Three disciplines. One team."
            subtitle="Deep domain physics, production-grade AI, and the training to put both in your engineers' hands."
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {pillars.map((pillar, i) => (
              <Reveal key={pillar.title} delay={i * 0.1} className="h-full">
                <div className="card card-hover h-full flex flex-col p-8 group">
                  <div className="mb-6 p-3 bg-slate-950 rounded-xl w-fit group-hover:scale-110 transition-transform">
                    {pillar.icon}
                  </div>
                  <h3 className="text-xl font-bold mb-4">{pillar.title}</h3>
                  <p className="text-slate-300 text-sm leading-relaxed mb-6 flex-1">{pillar.desc}</p>
                  <Link to={pillar.link} className="btn-ghost hover:gap-3">
                    Learn more <ArrowRight className="w-4 h-4" aria-hidden="true" />
                  </Link>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- Why ProReadyEngineer ---------- */}
      <section className="section-pad">
        <div className="container-site">
          <SectionHeading
            align="left"
            eyebrow="Why ProReadyEngineer"
            title={<>The team they call when the answer is <span className="text-gradient">&ldquo;impossible&rdquo;</span></>}
            subtitle="We are not a staffing firm. We are senior specialists who have designed, broken, fixed, and certified the systems you run."
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {differentiators.map((item, i) => (
              <Reveal key={item.title} delay={i * 0.08}>
                <div className="flex items-start gap-5">
                  <div className="shrink-0 p-3 rounded-xl bg-cyan-500/10 border border-cyan-500/20">
                    {item.icon}
                  </div>
                  <div>
                    <h3 className="text-lg font-bold mb-2">{item.title}</h3>
                    <p className="text-slate-300 text-sm leading-relaxed">{item.desc}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- Team ---------- */}
      <section className="section-pad bg-slate-900/30">
        <div className="container-site">
          <SectionHeading
            eyebrow="Our Team"
            title={<>Meet the <span className="text-gradient">Experts</span></>}
            subtitle="Deep academic knowledge and decades of industrial experience, brought together to solve your toughest engineering problems."
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-6xl mx-auto">
            {team.map((member, i) => (
              <TeamCard key={member.name} member={member} index={i} />
            ))}
          </div>
        </div>
      </section>

      {/* ---------- Featured work ---------- */}
      <section className="section-pad">
        <div className="container-site">
          <SectionHeading
            eyebrow="Featured Work"
            title="Selected work"
            subtitle="A sample of the problems we have already solved, and how."
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {featuredWork.map((work, i) => (
              <Reveal key={work.title} delay={i * 0.1} className="h-full">
                <Link to={work.link} className="card card-hover h-full flex flex-col p-8 group">
                  <span className="font-mono text-xs uppercase tracking-widest text-cyan-400 mb-4">
                    Case Study
                  </span>
                  <h3 className="text-xl font-bold mb-3 group-hover:text-cyan-300 transition-colors">
                    {work.title}
                  </h3>
                  <p className="text-slate-300 text-sm leading-relaxed mb-6 flex-1">{work.outcome}</p>
                  <span className="btn-ghost">
                    Read the case study <ArrowRight className="w-4 h-4" aria-hidden="true" />
                  </span>
                </Link>
              </Reveal>
            ))}
          </div>
          <Reveal className="text-center mt-12">
            <Link to="/case-studies" className="btn-ghost text-base">
              View all case studies <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </Link>
          </Reveal>
        </div>
      </section>

      {/* ---------- Closing CTA ---------- */}
      <CTABand />
    </div>
  );
};

export default Home;
