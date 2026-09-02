import React from 'react';
import { Link } from 'react-router-dom';
import { Flame, Brain, GraduationCap, CheckCircle2, ArrowRight, Briefcase, UserCheck, Presentation } from 'lucide-react';
import { Reveal, SectionHeading, CTABand, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';

type Practice = {
  id: string;
  index: string;
  eyebrow: string;
  title: string;
  icon: React.ReactElement;
  accent: string;        // text color for icon + checks
  glow: string;          // bg tint for the visual panel
  description: string;
  capabilities: string[];
  footnote?: React.ReactNode;
  visualLabel: string;
  visualTags: string[];
};

const practices: Practice[] = [
  {
    id: 'thermal-fluid',
    index: '01',
    eyebrow: 'Thermal Fluid Sciences',
    title: 'Thermal Fluid Sciences',
    icon: <Flame aria-hidden="true" />,
    accent: 'text-orange-400',
    glow: 'from-orange-500/10',
    description:
      'Expert consulting in high-temperature fluid dynamics and combustion systems, with a focus on gas turbine efficiency and emissions. From first-principles design to test-cell commissioning, we cover the full lifecycle of high-energy thermal hardware.',
    capabilities: [
      'Gas turbine combustion design & troubleshooting: DLN/DLE systems, lean blowout, combustion dynamics, and emissions compliance',
      'Hydrogen & alternative fuels: combustor adaptation for H2 blends, syngas, and liquid fuels including crude oil',
      'Emissions mapping & optimization: experimental design, data interpretation, and digital-twin-driven tuning',
      'High-pressure test cell & facility engineering: design, specification, sizing, and commissioning',
      'Test execution automation, including auto-mapping for faster, more repeatable campaigns',
      'Computational Fluid Dynamics (CFD) & conjugate heat transfer analysis',
      'Finite Element Analysis (FEA) & structural integrity assessment',
      'ASME pressure vessel & static equipment design',
    ],
    footnote: (
      <div className="flex flex-wrap gap-x-6 gap-y-2 mt-6">
        <Link to="/services/gas-turbine-combustion" className="btn-ghost">
          Combustion consulting in depth <ArrowRight className="w-4 h-4" aria-hidden="true" />
        </Link>
        <Link to="/services/test-cell-design" className="btn-ghost">
          Test cell design in depth <ArrowRight className="w-4 h-4" aria-hidden="true" />
        </Link>
      </div>
    ),
    visualLabel: 'Combustion Systems',
    visualTags: ['DLN / DLE', 'H2 & Flex-Fuel', 'CFD · CHT', 'ASME BPVC'],
  },
  {
    id: 'industrial-ai',
    index: '02',
    eyebrow: 'Industrial AI',
    title: 'Industrial AI & Data Analytics',
    icon: <Brain aria-hidden="true" />,
    accent: 'text-cyan-400',
    glow: 'from-cyan-500/10',
    description:
      'Bridging the gap between physics-based engineering and modern machine learning to find the patterns hidden in your data. Unlike generic data science firms, we understand the underlying physics of your systems, so models are accurate, physically consistent and explainable.',
    capabilities: [
      'Physics-informed machine learning & neural networks grounded in governing equations',
      'Computer vision for automated inspection and defect detection',
      'Bayesian methods for uncertainty quantification and decisions under sparse data',
      'Predictive maintenance & reliability models that anticipate failures before they happen',
      'Anomaly detection in high-frequency sensor data',
      'Digital twin development for performance monitoring and optimization',
      'Production-grade data pipelines & decision systems, not throwaway notebooks',
      'Test automation that closes the loop between experiment and model',
    ],
    footnote: (
      <Link to="/services/industrial-ai" className="btn-ghost mt-6">
        Industrial AI consulting in depth <ArrowRight className="w-4 h-4" aria-hidden="true" />
      </Link>
    ),
    visualLabel: 'Physics-First AI',
    visualTags: ['Physics-Informed ML', 'Computer Vision', 'Bayesian UQ', 'Digital Twins'],
  },
  {
    id: 'training',
    index: '03',
    eyebrow: 'Training',
    title: 'Training & Workshops',
    icon: <GraduationCap aria-hidden="true" />,
    accent: 'text-blue-400',
    glow: 'from-blue-500/10',
    description:
      'Instructor-led courses taught by industry veterans who have designed, tested, and fielded the systems they teach. We equip engineering teams with current tools and methods through hands-on technical training, on-site, online, or hybrid.',
    capabilities: [
      'Gas Turbine Emissions Mapping: our flagship 4-day weekend course, from first principles to expert level',
      'Advanced Combustion Fundamentals',
      'Gas Turbine Combustion',
      'Fundamentals of Turbomachinery',
      'Data Visualization & Advanced Analytics',
      'Applied Machine Learning & AI for Engineers',
      'CFD Best Practices & Simulation',
      'Custom corporate training programs aligned to your systems, data, and business goals',
    ],
    footnote: (
      <Link to="/training" className="btn-ghost mt-6">
        Explore the course catalog <ArrowRight className="w-4 h-4" aria-hidden="true" />
      </Link>
    ),
    visualLabel: 'Expert-Led Courses',
    visualTags: ['Instructor-Led', 'Hands-On Labs', 'Flagship: Emissions Mapping', 'Custom Corporate'],
  },
];

const processSteps = [
  {
    n: '01',
    title: 'Discover',
    desc: 'A focused technical conversation to understand your system, constraints, and what success looks like.',
  },
  {
    n: '02',
    title: 'Diagnose',
    desc: 'We dig into the data, drawings, and test results to isolate root causes, not symptoms.',
  },
  {
    n: '03',
    title: 'Solve',
    desc: 'Analysis, simulation, redesign, or model development, executed by senior engineers and validated against physics.',
  },
  {
    n: '04',
    title: 'Deploy',
    desc: 'Solutions delivered into your workflow: hardware changes, commissioned facilities, or production-grade software.',
  },
];

const engagementModels = [
  {
    icon: <Briefcase aria-hidden="true" />,
    title: 'Project-Based Consulting',
    desc: 'Scoped engagements with clear deliverables: a troubleshooting campaign, a test cell specification, a deployed model.',
  },
  {
    icon: <UserCheck aria-hidden="true" />,
    title: 'Embedded Expert Support',
    desc: 'A senior specialist integrated with your team for the duration of a program, on-site or remote.',
  },
  {
    icon: <Presentation aria-hidden="true" />,
    title: 'Workshops & Training',
    desc: 'Instructor-led courses and tailored workshops that raise your whole team’s capability.',
  },
];

const PracticeSection = ({ practice, flip }: { practice: Practice; flip: boolean }) => (
  <section id={practice.id} className="section-pad scroll-mt-24">
    <div className="container-site">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 items-center">
        {/* Copy + capabilities */}
        <Reveal className={flip ? 'lg:order-2' : ''}>
          <div className="flex items-center gap-3 mb-5">
            <span className="font-mono text-xs text-slate-400 tracking-widest">{practice.index}</span>
            <span className="h-px w-10 bg-slate-700" aria-hidden="true" />
            <span className="eyebrow">{practice.eyebrow}</span>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-5">{practice.title}</h2>
          <p className="text-slate-300 leading-relaxed mb-8">{practice.description}</p>
          <ul className="grid grid-cols-1 gap-3.5">
            {practice.capabilities.map((cap) => (
              <li key={cap} className="flex items-start gap-3 text-sm text-slate-300 leading-relaxed">
                <CheckCircle2 className={`w-5 h-5 shrink-0 mt-0.5 ${practice.accent}`} aria-hidden="true" />
                {cap}
              </li>
            ))}
          </ul>
          {practice.footnote}
        </Reveal>

        {/* Visual panel */}
        <Reveal delay={0.12} className={flip ? 'lg:order-1' : ''}>
          <div className="card relative overflow-hidden aspect-square max-w-md mx-auto w-full flex items-center justify-center">
            <div
              className={`absolute inset-0 bg-gradient-to-b ${practice.glow} via-transparent to-transparent pointer-events-none`}
              aria-hidden="true"
            />
            <div className="hero-backdrop opacity-40" aria-hidden="true" />
            <div className="relative z-10 text-center px-8">
              <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-slate-950/80 border border-slate-700/60 flex items-center justify-center">
                {React.cloneElement(practice.icon, {
                  className: `w-10 h-10 ${practice.accent}`,
                })}
              </div>
              <p className="font-mono text-xs uppercase tracking-widest text-slate-300 mb-6">
                {practice.visualLabel}
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {practice.visualTags.map((tag) => (
                  <span
                    key={tag}
                    className="font-mono text-[11px] uppercase tracking-wider text-slate-300 bg-slate-900/80 border border-slate-700/60 rounded-full px-3 py-1.5"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </div>
  </section>
);

const Services = () => {
  usePageMeta(
    'Consulting Services',
    'Gas turbine combustion design & troubleshooting, DLN/DLE and hydrogen fuels, high-pressure test cell engineering, CFD/FEA, physics-informed industrial AI, and expert-led training from ProReadyEngineer.'
  );

  return (
    <div>
      <PageHero
        eyebrow="What We Do"
        title={
          <>
            Specialized <span className="text-gradient">Engineering Services</span>
          </>
        }
        subtitle="Three deeply integrated practices (Thermal Fluid Sciences, Industrial AI, and expert-led Training) combining decades of gas turbine and thermal systems experience with advanced computational capability to solve the most complex engineering challenges."
      >
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          {practices.map((p) => (
            <a
              key={p.id}
              href={`#${p.id}`}
              className="font-mono text-xs uppercase tracking-widest text-slate-300 hover:text-cyan-400 bg-slate-900/70 border border-slate-700/70 hover:border-cyan-500/40 rounded-full px-4 py-2 transition-colors"
            >
              {p.index} / {p.title}
            </a>
          ))}
        </div>
      </PageHero>

      {practices.map((p, i) => (
        <PracticeSection key={p.id} practice={p} flip={i % 2 === 1} />
      ))}

      {/* How we engage */}
      <section className="section-pad relative overflow-hidden">
        <div className="absolute inset-0 -z-10 bg-hero-radial" aria-hidden="true" />
        <div className="container-site">
          <SectionHeading
            eyebrow="How We Engage"
            title="From first call to fielded solution"
            subtitle="A disciplined process honed across OEM programs, test campaigns, and field troubleshooting."
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {processSteps.map((step, i) => (
              <Reveal key={step.n} delay={i * 0.08}>
                <div className="card card-hover h-full p-6 relative">
                  <span className="font-mono text-xs text-cyan-400 tracking-widest">{step.n}</span>
                  <h3 className="text-lg font-bold mt-3 mb-2">{step.title}</h3>
                  <p className="text-sm text-slate-300 leading-relaxed">{step.desc}</p>
                  {i < processSteps.length - 1 && (
                    <ArrowRight
                      className="hidden lg:block absolute top-1/2 -right-4 -translate-y-1/2 w-4 h-4 text-slate-500"
                      aria-hidden="true"
                    />
                  )}
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* Engagement models */}
      <section className="section-pad pt-0">
        <div className="container-site">
          <SectionHeading
            eyebrow="Engagement Models"
            title="Work with us the way that fits"
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {engagementModels.map((m, i) => (
              <Reveal key={m.title} delay={i * 0.08}>
                <div className="card card-hover h-full p-8">
                  <div className="w-12 h-12 rounded-xl bg-slate-950/80 border border-slate-700/60 flex items-center justify-center text-cyan-400 mb-5">
                    {m.icon}
                  </div>
                  <h3 className="text-xl font-bold mb-3">{m.title}</h3>
                  <p className="text-sm text-slate-300 leading-relaxed">{m.desc}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <CTABand
        secondaryLabel="Browse Training Courses"
        secondaryTo="/training"
      />
    </div>
  );
};

export default Services;
