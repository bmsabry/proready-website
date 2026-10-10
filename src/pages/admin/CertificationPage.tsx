import React, { useCallback, useEffect, useState } from 'react';
import { Award, BadgeCheck, ChevronRight } from 'lucide-react';
import { api, reportError, type ViewState } from './lib';
import { EmptyState, Kpi, Notice, RefreshButton, Section } from './ui';
import { CandidateCard, money, type Candidate } from './CertificationTab';

/* Certification — the menu item for the instructor-examined tier.
 *
 * Everything waiting on the instructor, across every course, with the same
 * action cards as each course's Certification tab: fee-waiver requests,
 * interview windows to confirm, outcomes to record. Below that, one card per
 * course that opens its full Certification tab (settings, every candidate,
 * issued certificates). */

type CourseSummary = {
  product_code: string;
  product_title: string;
  course_code: string;
  course_title: string;
  enabled: boolean;
  price_cents: number;
  currency: string;
  exam_item_count: number;
  counts: {
    waiver_requests: number;
    windows_to_confirm: number;
    outcomes_to_record: number;
    upcoming_interviews: number;
    fees_due: number;
    in_progress: number;
    verified: number;
  };
  needs_you: number;
};

type Waiting = Candidate & {
  waiting_reason: string;
  product_title: string;
  course_code: string;
};

export type CertificationSummary = {
  needs_you: number;
  interview_minutes: number;
  courses: CourseSummary[];
  waiting: Waiting[];
};

const COUNT_LABELS: [keyof CourseSummary['counts'], string][] = [
  ['waiver_requests', 'Fee-waiver requests'],
  ['windows_to_confirm', 'Interview times to confirm'],
  ['outcomes_to_record', 'Outcomes to record'],
  ['upcoming_interviews', 'Interviews booked'],
  ['fees_due', 'Fees due before the interview'],
  ['in_progress', 'Examinations in progress'],
  ['verified', 'Verified certificates issued'],
];

export default function CertificationPage({
  onAuthError,
  go,
  onChanged,
}: {
  onAuthError: () => void;
  go: (v: ViewState) => void;
  /** Lets the sidebar badge refresh as soon as something is decided. */
  onChanged?: () => void;
}) {
  const [data, setData] = useState<CertificationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api<CertificationSummary>('/api/admin/academy/certification'));
      setError(null);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(key: string, fn: () => Promise<unknown>, done: string) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      setFlash(done);
      window.setTimeout(() => setFlash(null), 6000);
      await load();
      onChanged?.();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  const priceOf = (productCode: string) =>
    data?.courses.find((c) => c.product_code === productCode);

  return (
    <Section
      icon={<Award className="w-5 h-5 text-cyan-400" />}
      title="Certification"
      sub="The instructor-examined tier across all courses: fee-waiver requests, interview times to confirm and outcomes to record, then each course's full certification desk."
      actions={<RefreshButton onClick={() => void load()} loading={loading} />}
    >
      <div className="space-y-8">
        {error && <Notice kind="error">{error}</Notice>}
        {flash && <Notice kind="success">{flash}</Notice>}
        {!data && !error && <p className="text-sm text-slate-400">Loading…</p>}

        {data && (
          <>
            <div className="grid sm:grid-cols-3 gap-4">
              <Kpi
                label="Waiting on you"
                value={String(data.needs_you)}
                accent={data.needs_you ? 'amber' : 'slate'}
              />
              <Kpi
                label="Fee-waiver requests"
                value={String(data.courses.reduce((n, c) => n + c.counts.waiver_requests, 0))}
                accent="cyan"
              />
              <Kpi
                label="Verified certificates"
                value={String(data.courses.reduce((n, c) => n + c.counts.verified, 0))}
                accent="emerald"
              />
            </div>

            <section>
              <h2 className="text-base font-semibold text-white mb-3">Waiting on you</h2>
              {data.waiting.length === 0 ? (
                <EmptyState
                  icon={<BadgeCheck className="w-5 h-5" />}
                  title="Nothing is waiting on you"
                  hint="Fee-waiver requests, interview windows to confirm and interviews whose outcome is still to be recorded appear here, from every course."
                />
              ) : (
                <div className="space-y-4">
                  {data.waiting.map((c) => {
                    const course = priceOf(c.product_code);
                    return (
                      <CandidateCard
                        key={c.id}
                        c={c}
                        minutes={data.interview_minutes}
                        priceCents={course?.price_cents ?? 0}
                        currency={course?.currency ?? 'usd'}
                        busy={busy}
                        run={run}
                        context={
                          <div className="flex flex-wrap items-center gap-2 text-xs mb-3">
                            <span className="px-2 py-0.5 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-cyan-200">
                              {c.product_title}
                            </span>
                            <span className="text-amber-200">{c.waiting_reason}</span>
                            {c.course_code && (
                              <button
                                type="button"
                                className="ml-auto text-cyan-400 hover:text-cyan-300"
                                onClick={() =>
                                  go({
                                    page: 'courses',
                                    course: c.course_code,
                                    tab: 'certification',
                                  })
                                }
                              >
                                Open the course tab
                              </button>
                            )}
                          </div>
                        }
                      />
                    );
                  })}
                </div>
              )}
            </section>

            <section>
              <h2 className="text-base font-semibold text-white mb-3">Courses</h2>
              {data.courses.length === 0 ? (
                <EmptyState
                  icon={<Award className="w-5 h-5" />}
                  title="No course offers the examined tier yet"
                  hint="Switch it on in a course's Certification tab (Courses → the course → Certification)."
                />
              ) : (
                <div className="grid md:grid-cols-2 gap-4">
                  {data.courses.map((c) => (
                    <div key={c.product_code} className="card p-5 flex flex-col">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-white font-semibold">{c.product_title}</div>
                          <div className="text-xs text-slate-400 mt-0.5">
                            {c.enabled ? (
                              <>
                                Offered at {money(c.price_cents, c.currency)} · {c.exam_item_count}
                                -question bank
                              </>
                            ) : (
                              'Not offered at the moment'
                            )}
                          </div>
                        </div>
                        {c.needs_you > 0 && (
                          <span className="text-xs px-2 py-1 rounded-full border border-amber-700 text-amber-200 bg-amber-950/40 shrink-0">
                            {c.needs_you} waiting on you
                          </span>
                        )}
                      </div>
                      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                        {COUNT_LABELS.map(([k, label]) => (
                          <React.Fragment key={k}>
                            <dt className="text-slate-400">{label}</dt>
                            <dd
                              className={`text-right tabular-nums ${
                                c.counts[k] &&
                                [
                                  'waiver_requests',
                                  'windows_to_confirm',
                                  'outcomes_to_record',
                                ].includes(k)
                                  ? 'text-amber-200 font-semibold'
                                  : 'text-slate-200'
                              }`}
                            >
                              {c.counts[k]}
                            </dd>
                          </React.Fragment>
                        ))}
                      </dl>
                      <div className="mt-4 pt-3 border-t border-slate-800">
                        {c.course_code ? (
                          <button
                            type="button"
                            className="btn-secondary text-sm py-2 px-4"
                            onClick={() =>
                              go({ page: 'courses', course: c.course_code, tab: 'certification' })
                            }
                          >
                            Open the certification desk <ChevronRight className="w-4 h-4" />
                          </button>
                        ) : (
                          <p className="text-xs text-amber-300">
                            No course is linked to this product. Link one in the course's Settings
                            tab to manage its certification there.
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </Section>
  );
}
