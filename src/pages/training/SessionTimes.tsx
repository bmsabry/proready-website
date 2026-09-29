import React from 'react';
import { formatIsoDate } from '../../data/courseSnapshot';
import {
  COURSE_PLACES,
  hourBlocks,
  INSTRUCTOR_ZONE,
  SessionClock,
  timesByPlace,
} from '../../lib/sessionTimes';

// "November 2, 2026" -> "November 2"
const shortDate = (iso: string) => formatIsoDate(iso).replace(/, \d{4}$/, '');

/**
 * The per-country time cards and the hour-by-hour ruler on a live-course page.
 * Everything is derived from the start Bassam sets on his New York clock in the
 * admin, for the cohort's actual dates, with each country's own daylight-saving
 * rules — nothing on this component is typed by hand.
 */
const SessionTimes = ({
  clock,
  dayIsos,
  rulerGridClass,
}: {
  clock: SessionClock;
  dayIsos: string[];
  rulerGridClass: string;
}) => {
  const rows = timesByPlace(clock, dayIsos, COURSE_PLACES);
  if (rows.length === 0) {
    return (
      <p className="text-slate-300 text-sm mb-6">
        Session times for this cohort will be published here shortly.
      </p>
    );
  }
  // The ruler reads on the clock the start was set on (New York).
  const rulerZone = clock.local ? clock.zone : INSTRUCTOR_ZONE;
  const rulerLabel = rulerZone === INSTRUCTOR_ZONE ? 'Eastern Time' : rulerZone;
  const blocks = dayIsos[0] ? hourBlocks(clock, dayIsos[0], rulerZone) : [];
  const clockChange = rows.some((r) => r.periods.length > 1);

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-3">
        {rows.map((r) => {
          const [first, ...later] = r.periods;
          return (
            <div key={r.place} className="card card-hover p-5">
              <div className="text-xs font-mono uppercase tracking-wider text-slate-300 mb-1">
                {r.region ? `${r.region} · ${r.offsetLabel}` : r.offsetLabel}
              </div>
              <div className="text-base font-semibold text-cyan-400 mb-3">{r.place}</div>
              <div className="flex items-baseline gap-2 flex-wrap font-mono">
                <span className="text-xl font-bold text-white tabular-nums">{first.start}</span>
                {first.end && (
                  <>
                    <span className="text-slate-500">→</span>
                    <span className="text-xl font-bold text-white tabular-nums">{first.end}</span>
                  </>
                )}
              </div>
              {first.dayNote && (
                <div className="text-[11px] text-slate-300 mt-1">({first.dayNote})</div>
              )}
              {later.map((p) => (
                <div key={p.fromDayIso} className="text-[12px] text-amber-200 mt-2 leading-snug">
                  From {shortDate(p.fromDayIso)}: {p.start}
                  {p.end ? ` → ${p.end}` : ''}
                  {p.dayNote ? ` (${p.dayNote})` : ''}
                </div>
              ))}
            </div>
          );
        })}
      </div>
      <p className="text-[12px] text-slate-300 mb-6">
        {clockChange
          ? 'A clock change falls inside this cohort, so some local times move part-way through; each card shows the date its later times start.'
          : 'Times are for this cohort’s dates, with each country’s own daylight-saving rules applied.'}
      </p>

      {/* Hour-by-hour ruler — on Bassam's own clock so it stays compact */}
      {blocks.length > 0 && (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div className="text-xs font-mono uppercase tracking-wider text-slate-300">
              Hour-by-hour · {rulerLabel}
            </div>
            <div className="text-[11px] text-slate-300">10-minute break between hours</div>
          </div>
          <div className={`grid ${rulerGridClass} gap-2`}>
            {blocks.map((time, i) => (
              <div
                key={time}
                className="px-3 py-2 rounded-lg bg-slate-950/60 border border-slate-800 flex items-center gap-2"
              >
                <span className="text-[10px] font-mono uppercase tracking-wider text-slate-300 shrink-0">
                  Hr {i + 1}
                </span>
                <span className="text-slate-200 font-mono tabular-nums text-xs">{time}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
};

export default SessionTimes;
