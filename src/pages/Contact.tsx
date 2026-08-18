import React, { useState } from 'react';
import { Mail, Phone, MapPin, Send, CheckCircle2, Youtube, ShieldCheck, Clock, Users } from 'lucide-react';
import { Reveal, PageHero } from '../components/ui';
import { usePageMeta } from '../lib/meta';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

const inputClass =
  'w-full bg-slate-900/60 border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-100 placeholder:text-slate-400 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/30 transition-colors';

const labelClass = 'block text-xs font-mono font-medium text-slate-300 uppercase tracking-widest mb-2';

const RequiredMark = () => (
  <span className="text-cyan-400 ml-1" aria-hidden="true">
    *
  </span>
);

const Contact = () => {
  usePageMeta(
    'Contact',
    'Talk directly with senior gas turbine combustion, thermal-fluid, and industrial AI experts. Response within one business day. SAM.gov registered small business, CAGE 18X84.'
  );

  const [submitted, setSubmitted] = useState(false);
  const [ticketRef, setTicketRef] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Submits to our own support desk rather than a third-party form service.
   * The message becomes a tracked ticket: it is triaged, acknowledged by
   * email straight away, and the reply threads back to the same
   * conversation — none of which a fire-and-forget form relay can do.
   */
  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    if (!API_BASE) {
      setError(
        'The contact form is temporarily unavailable. Please email info@proreadyengineer.com directly.',
      );
      return;
    }

    setLoading(true);
    setError(null);

    const form = new FormData(e.currentTarget);
    const inquiry = String(form.get('inquiry_type') ?? '').trim();
    const company = String(form.get('company') ?? '').trim();
    const message = String(form.get('message') ?? '').trim();

    // The inquiry type and company are context for whoever reads this, so
    // they travel in the body rather than being dropped on the floor.
    const body = [
      message,
      '',
      inquiry ? `Inquiry type: ${inquiry}` : '',
      company ? `Company: ${company}` : '',
    ]
      .filter(Boolean)
      .join('\n');

    try {
      const res = await fetch(`${API_BASE}/api/support/contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: String(form.get('name') ?? '').trim(),
          email: String(form.get('email') ?? '').trim(),
          subject: inquiry ? `${inquiry} enquiry` : 'Website enquiry',
          message: body,
          website: String(form.get('website') ?? ''),
        }),
      });

      const data = (await res.json().catch(() => ({}))) as {
        ref?: string;
        detail?: unknown;
      };

      if (res.ok) {
        setTicketRef(data.ref ?? null);
        setSubmitted(true);
      } else {
        setError(
          typeof data.detail === 'string'
            ? data.detail
            : 'Something went wrong. Please try again, or email info@proreadyengineer.com.',
        );
      }
    } catch {
      setError(
        'Could not send your message. Please check your connection, or email info@proreadyengineer.com.',
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHero
        eyebrow="Contact"
        title={
          <>
            Let&rsquo;s Solve It <span className="text-gradient">Together</span>
          </>
        }
        subtitle="Whether you need a deep-dive combustion analysis, a custom AI model, or specialized training for your team, we're ready to help."
      />

      <section className="pb-20 lg:pb-28">
        <div className="container-site">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-10 lg:gap-14 items-start">
            {/* LEFT — contact info */}
            <Reveal className="lg:col-span-2">
              <div className="card p-8 space-y-8">
                <div className="space-y-6">
                  {([
                    {
                      icon: <Mail aria-hidden="true" />,
                      title: 'Email',
                      detail: 'info@proreadyengineer.com',
                      sub: 'Response within 1 business day',
                      href: 'mailto:info@proreadyengineer.com',
                    },
                    {
                      icon: <Youtube aria-hidden="true" />,
                      title: 'YouTube',
                      detail: '@ProReadyEngineer',
                      sub: 'Video tutorials & insights',
                      href: 'https://www.youtube.com/@ProReadyEngineer',
                      external: true,
                    },
                    {
                      icon: <Phone aria-hidden="true" />,
                      title: 'Phone',
                      detail: '+1 (513) 849-1016',
                      sub: 'Mon–Fri, 9am–5pm EST',
                      href: 'tel:+15138491016',
                    },
                    {
                      icon: <MapPin aria-hidden="true" />,
                      title: 'Office',
                      detail: '5325 Deerfield Blvd, # 148',
                      sub: 'Mason, OH 45040',
                    },
                  ] as {
                    icon: React.ReactElement;
                    title: string;
                    detail: string;
                    sub: string;
                    href?: string;
                    external?: boolean;
                  }[]).map((item) => (
                    <div key={item.title} className="flex gap-4">
                      <div className="w-11 h-11 rounded-xl bg-slate-950/80 border border-slate-700/60 flex items-center justify-center text-cyan-400 shrink-0">
                        {React.cloneElement(item.icon, { className: 'w-5 h-5' })}
                      </div>
                      <div>
                        <h3 className="text-xs font-mono uppercase tracking-widest text-slate-400">{item.title}</h3>
                        {item.href ? (
                          <a
                            href={item.href}
                            {...(item.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
                            className="font-medium text-slate-200 hover:text-cyan-400 transition-colors"
                          >
                            {item.detail}
                          </a>
                        ) : (
                          <p className="font-medium text-slate-200">{item.detail}</p>
                        )}
                        <p className="text-xs text-slate-300 mt-0.5">{item.sub}</p>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Federal contracting credentials */}
                <div className="rounded-xl bg-slate-950/60 border border-slate-700/50 p-5">
                  <h3 className="text-xs font-mono uppercase tracking-widest text-cyan-400 mb-3 flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                    Federal Contracting
                  </h3>
                  <dl className="font-mono text-xs text-slate-300 space-y-1.5">
                    <div className="flex justify-between gap-4">
                      <dt className="text-slate-400">SAM.gov</dt>
                      <dd className="text-slate-300">Registered Small Business</dd>
                    </div>
                    <div className="flex justify-between gap-4">
                      <dt className="text-slate-400">CAGE</dt>
                      <dd className="text-slate-300">18X84</dd>
                    </div>
                    <div className="flex justify-between gap-4">
                      <dt className="text-slate-400">UEI</dt>
                      <dd className="text-slate-300">RLHYXFN7JJN5</dd>
                    </div>
                    <div className="flex justify-between gap-4">
                      <dt className="text-slate-400">NAICS</dt>
                      <dd className="text-slate-300">541330 · 611430 · 541611</dd>
                    </div>
                  </dl>
                </div>

                {/* What to expect */}
                <div>
                  <h3 className="text-xs font-mono uppercase tracking-widest text-slate-400 mb-4">What to Expect</h3>
                  <ul className="space-y-3">
                    {[
                      { icon: <Clock aria-hidden="true" />, text: 'Response within 1 business day' },
                      { icon: <ShieldCheck aria-hidden="true" />, text: 'NDA-friendly: confidentiality from the first conversation' },
                      { icon: <Users aria-hidden="true" />, text: 'Direct access to senior experts, not account managers' },
                    ].map((item) => (
                      <li key={item.text} className="flex items-start gap-3 text-sm text-slate-300">
                        {React.cloneElement(item.icon, { className: 'w-4 h-4 text-cyan-400 shrink-0 mt-0.5' })}
                        {item.text}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </Reveal>

            {/* RIGHT — form */}
            <Reveal delay={0.1} className="lg:col-span-3">
              <div className="card relative overflow-hidden p-8 md:p-10">
                <div
                  className="absolute -top-20 right-0 w-72 h-48 bg-cyan-500/10 blur-[90px] rounded-full pointer-events-none"
                  aria-hidden="true"
                />
                {submitted ? (
                  <div className="text-center py-12" role="status">
                    <div className="w-20 h-20 bg-cyan-500/15 border border-cyan-500/30 rounded-full flex items-center justify-center mx-auto mb-6">
                      <CheckCircle2 className="w-10 h-10 text-cyan-400" aria-hidden="true" />
                    </div>
                    <h2 className="text-2xl font-bold mb-4">Message Received</h2>
                    <p className="text-slate-300 mb-4 max-w-md mx-auto">
                      Thank you for reaching out. You&rsquo;ll get a confirmation by email in the next
                      few minutes, and a reply from one of our principal engineers within one
                      business day.
                    </p>
                    {ticketRef && ticketRef !== '00000000' && (
                      <p className="text-sm text-slate-400 mb-8">
                        Your reference:{' '}
                        <span className="font-mono text-cyan-400">#{ticketRef}</span>
                        <span className="block text-xs text-slate-500 mt-1">
                          Replying to that email keeps everything in one conversation.
                        </span>
                      </p>
                    )}
                    <button
                      onClick={() => {
                        setSubmitted(false);
                        setTicketRef(null);
                      }}
                      className="btn-secondary"
                    >
                      Send Another Message
                    </button>
                  </div>
                ) : (
                  <form onSubmit={handleSubmit} className="space-y-6">
                    {error && (
                      <div
                        role="alert"
                        className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm"
                      >
                        {error}
                      </div>
                    )}

                    {/* Honeypot: off-screen and hidden from assistive tech, so
                        only a bot fills it. A filled value is accepted and
                        silently discarded server-side. */}
                    <div className="absolute left-[-9999px] w-px h-px overflow-hidden" aria-hidden="true">
                      <label htmlFor="website">Leave this field empty</label>
                      <input id="website" type="text" name="website" tabIndex={-1} autoComplete="off" />
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div>
                        <label htmlFor="name" className={labelClass}>
                          Full Name
                          <RequiredMark />
                        </label>
                        <input
                          required
                          id="name"
                          name="name"
                          type="text"
                          autoComplete="name"
                          aria-invalid={error ? true : undefined}
                          className={inputClass}
                          placeholder="Jane Smith"
                        />
                      </div>
                      <div>
                        <label htmlFor="email" className={labelClass}>
                          Email Address
                          <RequiredMark />
                        </label>
                        <input
                          required
                          id="email"
                          name="email"
                          type="email"
                          autoComplete="email"
                          aria-invalid={error ? true : undefined}
                          className={inputClass}
                          placeholder="jane@company.com"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div>
                        <label htmlFor="company" className={labelClass}>
                          Company
                        </label>
                        <input
                          id="company"
                          name="company"
                          type="text"
                          autoComplete="organization"
                          className={inputClass}
                          placeholder="Engineering Corp"
                        />
                      </div>
                      <div>
                        <label htmlFor="inquiry_type" className={labelClass}>
                          Inquiry Type
                        </label>
                        <select id="inquiry_type" name="inquiry_type" className={`${inputClass} appearance-none`}>
                          <option>Consulting Services</option>
                          <option>Training & Workshops</option>
                          <option>AI & Data Analytics</option>
                          <option>Other</option>
                        </select>
                      </div>
                    </div>

                    <div>
                      <label htmlFor="message" className={labelClass}>
                        Project Details
                        <RequiredMark />
                      </label>
                      <textarea
                        required
                        id="message"
                        name="message"
                        rows={5}
                        aria-invalid={error ? true : undefined}
                        className={`${inputClass} resize-none`}
                        placeholder="Tell us about your technical requirements..."
                      ></textarea>
                    </div>

                    <button
                      type="submit"
                      disabled={loading}
                      className="btn-primary w-full py-4 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {loading ? 'Sending...' : 'Send Inquiry'} <Send className="w-4 h-4" aria-hidden="true" />
                    </button>

                    <p className="text-[10px] font-mono text-slate-400 text-center uppercase tracking-widest">
                      Secure & Confidential Engineering Consultation
                    </p>
                  </form>
                )}
              </div>
            </Reveal>
          </div>
        </div>
      </section>
    </div>
  );
};

export default Contact;
