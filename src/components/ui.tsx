import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

/* ---------- Reveal: scroll-in animation wrapper ----------
   SEO/no-JS safe: content renders visible by default. On mount, elements
   still below the viewport are eased in as they scroll into view. */
export const Reveal = ({
  children,
  delay = 0,
  className,
  id,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
  id?: string;
}) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (el.getBoundingClientRect().top < window.innerHeight * 0.92) return;

    el.classList.add('reveal-pre');
    if (delay) el.style.transitionDelay = `${delay}s`;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          el.classList.add('reveal-in');
          io.disconnect();
        }
      },
      { rootMargin: '0px 0px -60px 0px' }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [delay]);

  return (
    <div ref={ref} id={id} className={className}>
      {children}
    </div>
  );
};

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
      <p className={`text-slate-300 leading-relaxed ${align === 'center' ? 'max-w-2xl mx-auto' : 'max-w-2xl'}`}>
        {subtitle}
      </p>
    )}
  </Reveal>
);

/* ---------- StatCounter: metric with count-up on first view ----------
   Renders the final value in static HTML; animates only on scroll-in. */
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
  const [n, setN] = useState(value);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (el.getBoundingClientRect().top < window.innerHeight * 0.95) return;

    let raf = 0;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting) return;
        io.disconnect();
        const dur = 1100;
        const t0 = performance.now();
        const tick = (t: number) => {
          const p = Math.min((t - t0) / dur, 1);
          setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
          if (p < 1) raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      },
      { rootMargin: '-40px' }
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [value]);

  return (
    <div ref={ref} className="text-center">
      <div className="font-display text-4xl md:text-5xl font-bold text-gradient tabular-nums">
        {prefix}{n.toLocaleString()}{suffix}
      </div>
      <div className="mt-2 text-xs font-mono uppercase tracking-widest text-slate-300">{label}</div>
    </div>
  );
};

/* ---------- CTABand: closing call-to-action section ---------- */
export const CTABand = ({
  title = 'Have an "unsolvable" engineering problem?',
  subtitle = 'Talk directly with the engineers who design, test, and fix demanding combustion and thermal-fluid systems.',
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
        <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[60%] h-48 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none" aria-hidden="true" />
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">{title}</h2>
        <p className="text-slate-300 max-w-2xl mx-auto mb-8">{subtitle}</p>
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
      <div className="anim-hero">
        {eyebrow && <span className="eyebrow mb-5">{eyebrow}</span>}
        <h1 className="text-4xl md:text-6xl font-bold tracking-tight mt-4 mb-6">{title}</h1>
        {subtitle && <p className="text-lg text-slate-300 max-w-3xl mx-auto leading-relaxed">{subtitle}</p>}
        {children}
      </div>
    </div>
  </section>
);
