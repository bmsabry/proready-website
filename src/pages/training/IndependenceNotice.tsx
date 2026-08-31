import React from 'react';
import { ShieldCheck } from 'lucide-react';

/* Legal independence notice shown on every training course page.
   Wording supplied by Bassam — keep it verbatim: it states the courses are
   built from public sources, original ProReadyEngineer tools and the
   instructor's own experience, carry no third-party confidential material,
   and have no OEM affiliation or endorsement. */
const IndependenceNotice = () => (
  <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 flex items-start gap-3">
    <ShieldCheck className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" aria-hidden="true" />
    <p className="text-xs text-slate-400 leading-relaxed">
      <span className="font-semibold text-slate-300">Independence notice:</span>{' '}
      This independent ProReadyEngineer course is based on established public
      engineering and regulatory sources, original ProReadyEngineer teaching
      tools, and the instructor’s professional experience. It contains no OEM
      or other third-party confidential or proprietary information and is not
      affiliated with or endorsed by any OEM.
    </p>
  </div>
);

export default IndependenceNotice;
