import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CalendarClock, CreditCard, Video } from 'lucide-react';
import { Reveal } from './ui';
import { CONSULT_PUBLIC } from '../lib/features';

/* "Consult an expert" call-to-action for Home and the Services pages.
 *
 * No price here, ever: rates are shown only inside the booking flow. The
 * copy is static so the prerendered HTML is the same for every visitor; the
 * live "Next available" line lives on /consult itself. */

export default function ConsultCallout({
  title = 'Need an expert on your problem today?',
  subtitle = 'Book a one-to-one video call with a gas turbine combustion expert, as soon as the same day. Pick a time from the live calendar; nothing is charged until after the meeting.',
}: {
  title?: string;
  subtitle?: string;
}) {
  // Hidden release: the section is not rendered at all (no empty band).
  if (!CONSULT_PUBLIC) return null;
  return (
    <section className="section-pad" aria-labelledby="consult-callout-title">
      <div className="container-site">
        <Reveal className="card relative overflow-hidden p-6 sm:p-10 lg:p-12">
          <div
            className="absolute -top-24 right-0 w-[50%] h-48 bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none"
            aria-hidden="true"
          />
          <div className="relative grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-8 lg:gap-12 items-center">
            <div>
              <span className="eyebrow mb-4">Consult an Expert</span>
              <h2 id="consult-callout-title" className="text-2xl md:text-3xl font-bold tracking-tight mt-3 mb-4">
                {title}
              </h2>
              <p className="text-slate-300 leading-relaxed mb-7 max-w-2xl">{subtitle}</p>
              <div className="flex flex-col sm:flex-row gap-3">
                <Link to="/consult" className="btn-primary">
                  Book a call <ArrowRight className="w-4 h-4" aria-hidden="true" />
                </Link>
                <Link to="/contact" className="btn-secondary">
                  Ask a question first
                </Link>
              </div>
            </div>
            <ul className="space-y-4">
              {[
                { icon: CalendarClock, text: 'Open times shown in your own time zone' },
                { icon: CreditCard, text: 'Save a card, pay nothing at booking' },
                { icon: Video, text: 'Meet on Google Meet, 30 minutes to 2 hours' },
              ].map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-center gap-3">
                  <span className="shrink-0 p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20">
                    <Icon className="w-5 h-5 text-cyan-400" aria-hidden="true" />
                  </span>
                  <span className="text-sm text-slate-200">{text}</span>
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
