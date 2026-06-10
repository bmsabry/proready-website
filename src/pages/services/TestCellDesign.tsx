import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2 } from 'lucide-react';
import { Reveal, SectionHeading, CTABand, PageHero } from '../../components/ui';
import { usePageMeta } from '../../lib/meta';

const capabilities = [
  'High-pressure combustion test cell design, from concept through commissioning',
  'Specification and procurement of air, fuel, quench, and measurement systems',
  'Gaseous fuel systems: natural gas, hydrogen blends, nitrogen doping, propane blending',
  'Liquid fuel systems, including dual-mode dry fuel and fuel-water emulsion operation',
  'Emissions sampling systems and probe design for high-temperature exhaust',
  'Data acquisition and control system specification and replacement',
  'Test asset protection logic and emergency sequencing',
  'Test execution automation and auto-mapping for faster campaigns',
  'ASME-code pressure vessels and static equipment, delivered to inspector acceptance',
];

const relatedWork = [
  {
    title: 'Fuel Supply Capability Expansion',
    desc: 'Higher-flow natural gas testing with nitrogen doping and propane blending: specified, procured, commissioned.',
    link: '/case-studies/case-study-fuel-supply-capability-expansion-specification-procurement-and-commissioning',
  },
  {
    title: 'Dual-Mode Liquid-Fuel Pumping System',
    desc: 'High-pressure pumping for dry fuel and fuel-water emulsion with advanced control and redundancy.',
    link: '/case-studies/dual-mode-liquid-fuel-pumping-system',
  },
  {
    title: 'Optimizing Test Cell Assembly',
    desc: 'Roughly two weeks of setup per campaign cut dramatically through assembly redesign.',
    link: '/case-studies/optimizing-test-cell-assembly',
  },
];

const faqs = [
  {
    q: 'Do you take responsibility for the whole facility or just the design?',
    a: 'Either, but we are at our best end to end: requirements, design, specification, vendor selection, procurement support, installation oversight, and commissioning. Several of our case studies cover exactly that scope, including fuel supply expansion and a dual-mode liquid-fuel pumping system.',
  },
  {
    q: 'Can you upgrade a working facility without long downtime?',
    a: 'That constraint shapes most of our facility work. We plan around test campaigns, stage installations, and commission in windows the operation can tolerate. The fuel systems and DAQ replacements we have delivered went into facilities that could not simply stop testing.',
  },
  {
    q: 'What fuels can your designs handle?',
    a: 'Natural gas at high flows, hydrogen and H2 blends, syngas, propane blending, nitrogen doping, and liquid fuels from diesel to crude oil, including fuel-water emulsions. Fuel flexibility is usually why clients call us rather than a general mechanical contractor.',
  },
  {
    q: 'Do you also design the measurement side?',
    a: 'Yes. Emissions sampling trains, probe and rake design for high-temperature exhaust, data acquisition systems, and the protection logic that keeps an expensive test article safe when something lets go.',
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
  name: 'Test Cell Design & Commissioning',
  serviceType: 'High-pressure test cell and facility engineering',
  provider: { '@id': 'https://proreadyengineer.com/#org' },
  areaServed: 'Worldwide',
  description:
    'Design, specification, procurement, and commissioning of high-pressure combustion test cells: air, fuel, quench, measurement, data acquisition, and protection systems.',
};

const TestCellDesign = () => {
  usePageMeta(
    'Test Cell Design & Commissioning',
    'High-pressure combustion test cell engineering: air, fuel, quench, and measurement systems specified, procured, and commissioned. Hydrogen-ready fuel systems, emissions sampling, DAQ, and protection logic.',
    { jsonLd: [serviceLd, faqLd] }
  );

  return (
    <div>
      <PageHero
        eyebrow="Services / Test Infrastructure"
        title="Test Cell Design & Commissioning"
        subtitle="High-pressure combustion test facilities, designed by engineers who have run test campaigns in them."
      />

      <section className="pb-8">
        <div className="container-site max-w-4xl">
          <Reveal>
            <div className="prose-dark text-base md:text-lg space-y-5">
              <p>
                A combustion test cell is an unforgiving piece of infrastructure. Undersize the air
                supply and every future campaign inherits the limit. Get the fuel system controls
                wrong and operators spend years fighting response lag. Skimp on protection logic
                and a single failed test article can cost more than the facility upgrade would
                have.
              </p>
              <p>
                We design test cells from the perspective of the people who use them, because we
                have been those people. Dr. Bassam Abdelnabi has specified and built high-pressure
                industrial test cells end to end, with the auxiliary air, fuel, quench,
                measurement, and control systems they need. Adam Bailey has led the mechanical
                design of complex combustion test rigs across GE heavy-duty frames for three
                decades.
              </p>
              <p>
                The same practice covers the systems around the cell:{' '}
                <Link to="/services/industrial-ai" className="text-cyan-400 hover:text-cyan-300">
                  data acquisition and test automation
                </Link>{' '}
                that raise daily data output, and{' '}
                <Link to="/services/gas-turbine-combustion" className="text-cyan-400 hover:text-cyan-300">
                  combustion expertise
                </Link>{' '}
                to make sure what you measure means something.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="section-pad bg-slate-900/30">
        <div className="container-site">
          <SectionHeading align="left" eyebrow="What We Do" title="Capabilities" />
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
          <SectionHeading eyebrow="Related Work" title="Facilities we have delivered" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {relatedWork.map((w) => (
              <Reveal key={w.title} className="h-full">
                <Link to={w.link} className="card card-hover h-full flex flex-col p-8 group">
                  <h3 className="text-lg font-bold mb-3 group-hover:text-cyan-300 transition-colors">{w.title}</h3>
                  <p className="text-slate-400 text-sm leading-relaxed mb-6 flex-1">{w.desc}</p>
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
                <p className="text-slate-400 text-sm leading-relaxed">{f.a}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <CTABand
        title="Planning a test facility, or fighting one?"
        subtitle="Tell us what you need to test and at what conditions. We will tell you what the facility has to look like."
      />
    </div>
  );
};

export default TestCellDesign;
