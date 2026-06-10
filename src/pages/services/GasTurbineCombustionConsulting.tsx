import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2 } from 'lucide-react';
import { Reveal, SectionHeading, CTABand, PageHero } from '../../components/ui';
import { usePageMeta } from '../../lib/meta';

const capabilities = [
  'DLN/DLE combustion system design, tuning, and troubleshooting',
  'Combustion dynamics diagnosis and mitigation, from sensing to hardware changes',
  'Lean blowout margin assessment and operability mapping',
  'Hydrogen and flex-fuel conversion: H2 blends, syngas, and liquid fuels including crude oil',
  'Emissions mapping campaigns: experimental design, execution, and digital-twin-driven tuning',
  'NOx and CO compliance work, from root cause to verified fix',
  'CFD and conjugate heat transfer analysis of combustor hardware',
  'Combustor test rig design and test campaign planning',
];

const relatedWork = [
  {
    title: 'Multichannel Emissions Sampling',
    desc: 'A faster, simpler multichannel sampling system delivered in eight weeks at 62% lower cost.',
    link: '/case-studies/multichannel-emissions-sampling',
  },
  {
    title: 'Extending Emissions Probe Durability',
    desc: 'Probe cooling and structural redesign for extreme thermal gradients in high-temperature exhaust.',
    link: '/case-studies/extending-emissions-probe-durability',
  },
  {
    title: 'Transitioning DLE Combustion to 100% Hydrogen',
    desc: 'What actually happens to flame position, dynamics, and NOx when you push H2 fractions to 100%.',
    link: '/insights/transitioning-dle-combustion-systems-to-100-hydrogen',
  },
];

const faqs = [
  {
    q: 'Which combustion systems do you work on?',
    a: 'Industrial gas turbines and aeroderivatives, with deep experience in Dry Low NOx (DLN) and Dry Low Emissions (DLE) systems. Our team includes engineers who designed and patented DLN hardware at GE, and we have worked across GE frames including 6B, 7EA, 9E, 7FA, and 9FA as well as aviation combustors.',
  },
  {
    q: 'Can you help us burn hydrogen in an existing combustor?',
    a: 'Yes. We assess flashback and flameholding risk, flame position shift, dynamics, and NOx behavior for H2 blends up to 100%, then define the hardware and control changes needed. We have hands-on experience with hydrogen, syngas, and liquid fuels including crude oil.',
  },
  {
    q: 'Do you run emissions mapping in the field?',
    a: 'Yes. We design the test matrix, run the mapping campaign, and use digital twin models to tune the engine against its compliance limits. We also teach this as a 5-day course, Gas Turbine Emissions Mapping.',
  },
  {
    q: 'How does an engagement usually start?',
    a: 'With a focused technical call. You describe the problem and constraints; we tell you honestly whether we can help, what we would do first, and what it costs. No long discovery phase before you hear anything useful.',
  },
];

const faqLd = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: faqs.map((f) => ({
    '@type': 'Question',
    name: f.q,
    acceptedAnswer: { '@type': 'Answer', text: f.a },
  })),
};

const serviceLd = {
  '@context': 'https://schema.org',
  '@type': 'Service',
  name: 'Gas Turbine Combustion Consulting',
  serviceType: 'Gas turbine combustion engineering consulting',
  provider: { '@id': 'https://proreadyengineer.com/#org' },
  areaServed: 'Worldwide',
  description:
    'DLN/DLE combustion design and troubleshooting, hydrogen and flex-fuel conversion, combustion dynamics, lean blowout, emissions mapping and compliance.',
};

const GasTurbineCombustionConsulting = () => {
  usePageMeta(
    'Gas Turbine Combustion Consulting',
    'DLN/DLE combustion design and troubleshooting, hydrogen and flex-fuel conversion, combustion dynamics, lean blowout, and emissions compliance. Ex-GE combustion engineers with field and test-cell experience.',
    { jsonLd: [serviceLd, faqLd] }
  );

  return (
    <div>
      <PageHero
        eyebrow="Services / Combustion"
        title="Gas Turbine Combustion Consulting"
        subtitle="Design, troubleshooting, and emissions compliance for DLN/DLE combustion systems, from engineers who spent their careers inside GE combustors."
      />

      <section className="pb-8">
        <div className="container-site max-w-4xl">
          <Reveal>
            <div className="prose-dark text-base md:text-lg space-y-5">
              <p>
                Combustion problems rarely announce themselves politely. They show up as a dynamics
                alarm at 3 a.m., a NOx exceedance letter from the regulator, or a unit that trips on
                lean blowout every time the grid asks it to turn down. By the time we get the call,
                someone has usually already tried the obvious fixes.
              </p>
              <p>
                That is the work we do. ProReadyEngineer's combustion practice is led by
                Dr. Bassam Abdelnabi, a Ph.D. aerospace engineer with over a decade leading
                combustion R&amp;D at GE Aerospace and GE Global Research, alongside John
                Battaglioli, who holds multiple patents in Dry Low NOx combustion and 45 years of
                power and aviation experience. We have designed combustors, broken them in test
                cells, certified them, and tuned them in the field.
              </p>
              <p>
                Because we also build and commission{' '}
                <Link to="/services/test-cell-design" className="text-cyan-400 hover:text-cyan-300">
                  high-pressure combustion test facilities
                </Link>{' '}
                and develop{' '}
                <Link to="/services/industrial-ai" className="text-cyan-400 hover:text-cyan-300">
                  physics-grounded analytics
                </Link>
                , we can take a problem from first measurement to verified fix without handing it
                between three different vendors.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="section-pad bg-slate-900/30">
        <div className="container-site">
          <SectionHeading
            align="left"
            eyebrow="What We Do"
            title="Capabilities"
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-10 gap-y-4 max-w-5xl">
            {capabilities.map((c) => (
              <Reveal key={c}>
                <div className="flex items-start gap-3">
                  <CheckCircle2 className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
                  <p className="text-slate-300 text-sm leading-relaxed">{c}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section-pad">
        <div className="container-site">
          <SectionHeading
            eyebrow="Related Work"
            title="Combustion problems we have solved"
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {relatedWork.map((w) => (
              <Reveal key={w.title} className="h-full">
                <Link to={w.link} className="card card-hover h-full flex flex-col p-8 group">
                  <h3 className="text-lg font-bold mb-3 group-hover:text-cyan-300 transition-colors">{w.title}</h3>
                  <p className="text-slate-300 text-sm leading-relaxed mb-6 flex-1">{w.desc}</p>
                  <span className="btn-ghost">
                    Read more <ArrowRight className="w-4 h-4" aria-hidden="true" />
                  </span>
                </Link>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section-pad bg-slate-900/30">
        <div className="container-site max-w-4xl">
          <SectionHeading align="left" eyebrow="FAQ" title="Common questions" />
          <div className="space-y-8">
            {faqs.map((f) => (
              <Reveal key={f.q}>
                <h3 className="text-lg font-semibold mb-2">{f.q}</h3>
                <p className="text-slate-300 text-sm leading-relaxed">{f.a}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <CTABand
        title="Tell us what your combustor is doing"
        subtitle="Dynamics, blowout, emissions, fuel flexibility: describe the symptom and we will tell you what we would check first."
        secondaryLabel="Emissions Mapping course"
        secondaryTo="/training/gas-turbine-emissions-mapping"
      />
    </div>
  );
};

export default GasTurbineCombustionConsulting;
