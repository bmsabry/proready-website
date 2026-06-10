import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2 } from 'lucide-react';
import { Reveal, SectionHeading, CTABand, PageHero } from '../../components/ui';
import { usePageMeta } from '../../lib/meta';

const capabilities = [
  'Physics-informed machine learning grounded in the governing equations of your system',
  'Computer vision for automated inspection and defect detection',
  'Predictive maintenance and reliability models built on real failure physics',
  'Anomaly detection in high-frequency sensor and test data',
  'Bayesian methods for decisions under sparse, expensive data',
  'Digital twins for performance monitoring and emissions optimization',
  'Test automation that closes the loop between experiment and model',
  'Production-grade data pipelines and decision systems, not throwaway notebooks',
];

const relatedWork = [
  {
    title: 'New High-Performance Data Acquisition System',
    desc: 'A decades-old bottleneck replaced in 12 weeks, with a working MVP in the first three.',
    link: '/case-studies/new-highperformance-data-acquisition-system',
  },
  {
    title: 'Enhancing Test Execution Cost & Efficiency',
    desc: '40% more data points per day and 50% lower staffing per test through automation.',
    link: '/case-studies/enhancing-test-execution-cost-efficiency',
  },
  {
    title: 'Test Asset Protection Logic',
    desc: 'Automated protection sequencing that shields six-figure test articles from failure scenarios.',
    link: '/case-studies/test-asset-protection-logic',
  },
];

const faqs = [
  {
    q: 'How are you different from a generic data science firm?',
    a: 'Our AI lead, Dr. Ammar Abdilghanie, holds a PhD in mechanical engineering and has deployed industrial AI at Blue Origin, Baker Hughes, and Halliburton. We understand the physics of the machines generating your data, so our models stay consistent with how the hardware actually behaves, and engineers can interrogate why a model made a prediction.',
  },
  {
    q: 'Our data is messy and scattered. Is that a problem?',
    a: 'It is normal. Most industrial datasets we inherit live in historians, CSV exports, and test logs with inconsistent naming. Building the pipeline that turns that into something trustworthy is usually the first third of the project, and we scope it that way from the start.',
  },
  {
    q: 'Do you hand over production systems or just studies?',
    a: 'Production systems. Several of our engagements have replaced legacy data acquisition and test execution tooling that operators now use daily. We deliver deployed software with documentation and training, and your team owns it.',
  },
  {
    q: 'What does a sensible first project look like?',
    a: 'Small and measurable: one machine, one failure mode, one test stand. A few weeks to a working prototype against your real data, then a decision point on whether to scale. We would rather earn the larger engagement than sell it up front.',
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
  name: 'Industrial AI & Machine Learning Consulting',
  serviceType: 'Industrial AI and data analytics consulting',
  provider: { '@id': 'https://proreadyengineer.com/#org' },
  areaServed: 'Worldwide',
  description:
    'Physics-informed machine learning, predictive maintenance, anomaly detection, computer vision, and digital twins for aerospace, energy, and manufacturing.',
};

const IndustrialAIConsulting = () => {
  usePageMeta(
    'Industrial AI & Machine Learning Consulting',
    'Physics-informed machine learning, predictive maintenance, anomaly detection, and digital twins for aerospace, energy, and manufacturing. Built by PhD engineers who understand the hardware behind the data.',
    { jsonLd: [serviceLd, faqLd] }
  );

  return (
    <div>
      <PageHero
        eyebrow="Services / Industrial AI"
        title="Industrial AI & Machine Learning Consulting"
        subtitle="Machine learning that respects physics, built by engineers who have run the machines your data comes from."
      />

      <section className="pb-8">
        <div className="container-site max-w-4xl">
          <Reveal>
            <div className="prose-dark text-base md:text-lg space-y-5">
              <p>
                Most industrial AI projects fail the same way: a model that looked great in a
                notebook meets a plant, a test cell, or a flight program, and quietly stops being
                used. The model was fit to data but blind to physics, so the first time conditions
                drift outside the training set, operators stop trusting it.
              </p>
              <p>
                We build models the other way around. Start from the governing physics of the
                machine, use data to capture what the equations cannot, and keep every prediction
                explainable to the engineer who has to act on it. That approach comes from
                experience: our team has deployed analytics and automation at Blue Origin, Baker
                Hughes, Halliburton, and GE, on systems where a wrong prediction costs real money
                or worse.
              </p>
              <p>
                The same team designs{' '}
                <Link to="/services/test-cell-design" className="text-cyan-400 hover:text-cyan-300">
                  the test infrastructure
                </Link>{' '}
                and{' '}
                <Link to="/services/gas-turbine-combustion" className="text-cyan-400 hover:text-cyan-300">
                  the combustion systems
                </Link>{' '}
                that generate the data, which means we know what the sensors are actually
                measuring, where they lie, and which features matter.
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
          <SectionHeading eyebrow="Related Work" title="Deployed, not demoed" />
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
        title="Have data you suspect is worth more?"
        subtitle="Bring one problem and a sample of the data. We will tell you what is achievable and what it would take."
      />
    </div>
  );
};

export default IndustrialAIConsulting;
