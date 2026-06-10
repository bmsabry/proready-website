import React, { useEffect, useRef, useState } from 'react';
import { motion, useInView } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

/* ---------- Reveal: standard scroll-in animation wrapper ---------- */
export const Reveal = ({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) => (
  <motion.div
    initial={{ opacity: 0, y: 24 }}
    whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true, margin: '-60px' }}
    transition={{ duration: 0.55, delay, ease: [0.21, 0.47, 0.32, 0.98] }}
    className={className}
  >
    {children}
  </motion.div>
);

/* ---------- SectionHeading: eyebrow + title + subtitle ---------- */
export const SectionHeading = ({
  eyebrow,
  title,
  subtitle,
  align = 'center',
}: {
  eyebrow?: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  align?: 'center' | 'left';
}) => (
  <Reveal className={align === 'center' ? 'text-center mb-14' : 'mb-12'}>
    {eyebrow && <span className="eyebrow mb-4">{eyebrow}</span>}
    <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-3 mb-4">{title}</h2>
    {subtitle && (
      <p className={`text-slate-400 leading-relaxed ${align === 'center' ? 'max-w-2xl mx-auto' : 'max-w-2xl'}`}>
        {subtitle}
      </p>
    )}
  </Reveal>
);

/* ---------- StatCounter: animated count-up metric ---------- */
export const StatCounter = ({
  value,
  suffix = '',
  prefix = '',
  label,
}: {
  value: number;
  suffix?: string;
  prefix?: string;
  label: string;
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: '-40px' });
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!inView) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { setN(value); return; }
    const dur = 1200;
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min((t - t0) / dur, 1);
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, value]);

  return (
    <div ref={ref} className="text-center">
      <div className="font-display text-4xl md:text-5xl font-bold text-gradient tabular-nums">
        {prefix}{n.toLocaleString()}{suffix}
      </div>
      <div className="mt-2 text-xs font-mono uppercase tracking-widest text-slate-400">{label}</div>
    </div>
  );
};

/* ---------- CTABand: closing call-to-action section ---------- */
export const CTABand = ({
  title = 'Have an "unsolvable" engineering problem?',
  subtitle = "Talk directly with the experts who design, test, and fix the world's most demanding combustion and thermal-fluid systems.",
  primaryLabel = 'Consult with Experts',
  primaryTo = '/contact',
  secondaryLabel,
  secondaryTo,
}: {
  title?: string;
  subtitle?: string;
  primaryLabel?: string;
  primaryTo?: string;
  secondaryLabel?: string;
  secondaryTo?: string;
}) => (
  <section className="section-pad relative overflow-hidden">
    <div className="absolute inset-0 -z-10 bg-hero-radial" />
    <div className="container-site">
      <Reveal className="card relative overflow-hidden text-center px-6 py-16 md:px-16">
        <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[60%] h-48 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none" />
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">{title}</h2>
        <p className="text-slate-400 max-w-2xl mx-auto mb-8">{subtitle}</p>
        <div className="flex flex-col sm:flex-row justify-center gap-4">
          <Link to={primaryTo} className="btn-primary">
            {primaryLabel} <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </Link>
          {secondaryLabel && secondaryTo && (
            <Link to={secondaryTo} className="btn-secondary">{secondaryLabel}</Link>
          )}
        </div>
      </Reveal>
    </div>
  </section>
);

/* ---------- PageHero: standard interior-page header ---------- */
export const PageHero = ({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children?: React.ReactNode;
}) => (
  <section className="relative pt-36 pb-16 lg:pt-44 lg:pb-20 overflow-hidden">
    <div className="hero-backdrop" />
    <div className="absolute inset-0 -z-10 bg-hero-radial" />
    <div className="container-site text-center">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
        {eyebrow && <span className="eyebrow mb-5">{eyebrow}</span>}
        <h1 className="text-4xl md:text-6xl font-bold tracking-tight mt-4 mb-6">{title}</h1>
        {subtitle && <p className="text-lg text-slate-400 max-w-3xl mx-auto leading-relaxed">{subtitle}</p>}
        {children}
      </motion.div>
    </div>
  </section>
);
