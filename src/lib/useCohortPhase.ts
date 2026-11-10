import { useEffect, useState } from 'react';
import { CohortPhase, SessionClock, cohortPhase } from './sessionTimes';

/**
 * Where a cohort stands right now, for a page to show.
 *
 * Always 'upcoming' on the first render, then corrected once the browser has
 * read the clock. Deciding during the first render would make the prerendered
 * HTML (built on the day of the last deploy) disagree with the browser, which
 * React treats as an error. It also re-checks once a minute, so a page left
 * open across a session start does not keep offering registration.
 */
export function useCohortPhase(clock: SessionClock, dayIsos: string[]): CohortPhase {
  const [phase, setPhase] = useState<CohortPhase>('upcoming');
  const daysKey = dayIsos.join(',');
  useEffect(() => {
    const check = () => setPhase(cohortPhase(clock, daysKey ? daysKey.split(',') : [], Date.now()));
    check();
    const timer = window.setInterval(check, 60_000);
    return () => window.clearInterval(timer);
  }, [clock.local, clock.zone, clock.utc, daysKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return phase;
}
