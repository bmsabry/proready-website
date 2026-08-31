import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, PlayCircle, Users } from 'lucide-react';

export type FormatKey = 'live' | 'ondemand';

export type FormatOption = {
  key: FormatKey;
  title: string;
  price: string;
  meta: string;
  to: string;
};

/* Two-format chooser shown on both Micro Gas Turbine Design pages.
 *
 * The course is ONE offering with two delivery methods — same seven-module
 * curriculum, same materials, same certificate; only the delivery differs.
 * So each page names both formats with their prices and lets the visitor
 * jump straight to the other, the standard pattern for multi-format
 * courses. The page it sits on is marked as the current format.
 */
const FormatSwitcher = ({
  options,
  current,
}: {
  options: FormatOption[];
  current: FormatKey;
}) => (
  <div className="mb-10">
    <div className="text-xs font-mono uppercase tracking-wider text-slate-300 mb-3">
      Offered two ways — same curriculum, same materials, same certificate
    </div>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-2xl">
      {options.map((o) => {
        const active = o.key === current;
        const icon =
          o.key === 'live' ? (
            <Users className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
          ) : (
            <PlayCircle className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
          );
        const body = (
          <>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <span className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-slate-300">
                {icon}
                {o.title}
              </span>
              {active ? (
                <span className="text-[10px] font-mono uppercase tracking-wider text-cyan-300 px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 shrink-0">
                  You're viewing
                </span>
              ) : (
                <ArrowRight
                  className="w-4 h-4 text-slate-500 group-hover:text-cyan-300 transition-colors shrink-0"
                  aria-hidden="true"
                />
              )}
            </div>
            <div className="text-lg font-bold text-white tabular-nums leading-tight">
              {o.price}
            </div>
            <div className="text-[11px] font-mono text-slate-400 mt-1">{o.meta}</div>
          </>
        );
        return active ? (
          <div
            key={o.key}
            className="rounded-xl border border-cyan-500/50 bg-cyan-500/10 p-4"
            aria-current="page"
          >
            {body}
          </div>
        ) : (
          <Link
            key={o.key}
            to={o.to}
            className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 hover:border-cyan-500/40 transition-colors group"
          >
            {body}
          </Link>
        );
      })}
    </div>
  </div>
);

export default FormatSwitcher;
