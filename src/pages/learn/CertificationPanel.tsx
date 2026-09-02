import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Award,
  BadgeCheck,
  CalendarClock,
  Check,
  ClipboardCheck,
  Copy,
  Download,
  ExternalLink,
  Linkedin,
  ShieldCheck,
  Video,
} from 'lucide-react';
import {
  academy,
  ApiError,
  certificateFileUrl,
  CertificationStatus,
  IssuedCertificate,
} from '../../lib/academyApi';

/* Certification panel — both tiers, on the course dashboard.
 *
 * Tier 1 issues itself: the API re-checks completion every time this panel
 * loads and after every quiz/heartbeat, so the panel only ever has to show
 * the state. The one thing it must collect is the learner's name.
 *
 * Tier 2 is a strict state machine on the server; this panel renders the
 * current step and offers exactly the action that step allows. */

const fmtDate = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '';

const money = (cents: number, currency: string) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
    maximumFractionDigits: 0,
  }).format(cents / 100);

const CopyLink = ({ text }: { text: string }) => {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn-ghost text-sm py-2 px-3"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          window.setTimeout(() => setDone(false), 2000);
        } catch {
          /* clipboard blocked — the link is visible on screen anyway */
        }
      }}
    >
      {done ? <Check className="w-4 h-4" aria-hidden="true" /> : <Copy className="w-4 h-4" aria-hidden="true" />}
      {done ? 'Copied' : 'Copy verification link'}
    </button>
  );
};

/* The issued-credential block, shared by both tiers. */
const CertificateCard = ({ cert }: { cert: IssuedCertificate }) => (
  <div className="grid md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-6 items-start">
    <a
      href={certificateFileUrl(cert.code, 'pdf')}
      target="_blank"
      rel="noopener"
      className="block rounded-lg overflow-hidden border border-slate-700/70 bg-white shadow-glow-cyan"
      aria-label={`Open your ${cert.title} as a PDF`}
    >
      {cert.preview_url ? (
        <img
          src={certificateFileUrl(cert.code, 'png')}
          alt={`${cert.title} issued to ${cert.learner_name}`}
          className="w-full h-auto block"
          loading="lazy"
        />
      ) : (
        <div className="aspect-[11/8.5] flex items-center justify-center text-slate-500 text-sm">
          Preview unavailable. Open the PDF
        </div>
      )}
    </a>
    <div>
      <div className="text-xs font-mono uppercase tracking-widest text-cyan-400">
        Issued {fmtDate(cert.issued_at)}
        {cert.exam_date ? ` · examined ${fmtDate(cert.exam_date)}` : ''}
      </div>
      <h3 className="text-lg font-semibold text-white mt-1">{cert.title}</h3>
      <p className="text-sm text-slate-300 mt-1">
        Issued to <span className="text-white">{cert.learner_name}</span>
      </p>
      <dl className="mt-3 text-xs text-slate-400 space-y-1">
        <div className="flex gap-2">
          <dt className="w-24 shrink-0">Credential ID</dt>
          <dd className="font-mono text-slate-200">{cert.code}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-24 shrink-0">Verify at</dt>
          <dd>
            <a href={cert.verify_url} className="text-cyan-400 hover:text-cyan-300 underline-offset-2 hover:underline" target="_blank" rel="noopener">
              {cert.verify_url.replace(/^https?:\/\//, '')}
            </a>
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-24 shrink-0">Signature</dt>
          <dd className="font-mono text-slate-300">{cert.signature_fingerprint}</dd>
        </div>
      </dl>
      <div className="flex flex-wrap gap-2 mt-4">
        <a
          href={certificateFileUrl(cert.code, 'pdf')}
          className="btn-primary text-sm py-2 px-4"
          target="_blank"
          rel="noopener"
        >
          <Download className="w-4 h-4" aria-hidden="true" /> Download PDF
        </a>
        <a
          href={cert.linkedin.add_to_profile}
          className="btn-secondary text-sm py-2 px-4"
          target="_blank"
          rel="noopener"
        >
          <Linkedin className="w-4 h-4" aria-hidden="true" /> Add to LinkedIn profile
        </a>
        <a
          href={cert.linkedin.share}
          className="btn-secondary text-sm py-2 px-4"
          target="_blank"
          rel="noopener"
        >
          <ExternalLink className="w-4 h-4" aria-hidden="true" /> Share on LinkedIn
        </a>
        <CopyLink text={cert.verify_url} />
      </div>
      <p className="text-xs text-slate-500 mt-3">
        "Add to profile" opens LinkedIn's Licenses &amp; Certifications form pre-filled. "Share"
        posts the verification page, which shows the certificate itself.
      </p>
    </div>
  </div>
);

const NameForm = ({
  initial,
  onSaved,
}: {
  initial: string;
  onSaved: (name: string) => void;
}) => {
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <form
      className="mt-4 flex flex-col sm:flex-row gap-3 sm:items-end"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError('');
        try {
          const res = await academy.setName(name);
          onSaved(res.full_name);
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Could not save your name.');
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="flex-1 block">
        <span className="text-xs font-mono uppercase tracking-widest text-slate-400">
          Full name, exactly as it should appear on the certificate
        </span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
          placeholder="e.g. Amira Haddad"
          required
          minLength={2}
          maxLength={120}
        />
      </label>
      <button type="submit" className="btn-primary text-sm py-2.5 px-4" disabled={busy}>
        {busy ? 'Saving…' : 'Save name'}
      </button>
      {error && <p className="text-sm text-red-300 sm:basis-full">{error}</p>}
    </form>
  );
};

const SlotsForm = ({
  code,
  onDone,
}: {
  code: string;
  onDone: (adv: CertificationStatus['advanced']) => void;
}) => {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const [slots, setSlots] = useState(['', '', '']);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const minLocal = new Date(Date.now() + 24 * 3600 * 1000).toISOString().slice(0, 16);
  return (
    <form
      className="mt-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const isos = slots
          .filter((s) => s)
          .map((s) => new Date(s).toISOString());
        if (isos.length === 0) {
          setError('Propose at least one window.');
          return;
        }
        setBusy(true);
        setError('');
        try {
          onDone(await academy.proposeSlots(code, isos, tz, note));
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Could not send your windows.');
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="text-sm text-slate-300">
        Propose up to three 60-minute windows that suit you (your clock: {tz}). Your examiner
        confirms one and you receive the meeting link by email.
      </p>
      <div className="grid sm:grid-cols-3 gap-3 mt-3">
        {slots.map((s, i) => (
          <label key={i} className="block">
            <span className="text-xs font-mono uppercase tracking-widest text-slate-400">
              Window {i + 1}
            </span>
            <input
              type="datetime-local"
              value={s}
              min={minLocal}
              onChange={(e) => setSlots(slots.map((v, j) => (j === i ? e.target.value : v)))}
              className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
              required={i === 0}
            />
          </label>
        ))}
      </div>
      <label className="block mt-3">
        <span className="text-xs font-mono uppercase tracking-widest text-slate-400">
          Note for your examiner (optional)
        </span>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
          placeholder="e.g. Mornings in my time zone are best"
        />
      </label>
      {error && <p className="text-sm text-red-300 mt-2">{error}</p>}
      <button type="submit" className="btn-primary text-sm py-2.5 px-4 mt-4" disabled={busy}>
        <CalendarClock className="w-4 h-4" aria-hidden="true" />
        {busy ? 'Sending…' : 'Send my windows'}
      </button>
    </form>
  );
};

const Step = ({
  n,
  title,
  children,
  active,
}: {
  n: number;
  title: string;
  children?: React.ReactNode;
  active?: boolean;
}) => (
  <div className={`flex gap-3 ${active ? '' : 'opacity-60'}`}>
    <div className="w-7 h-7 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 font-mono text-xs flex items-center justify-center shrink-0">
      {n}
    </div>
    <div>
      <div className="text-sm font-semibold text-white">{title}</div>
      {children && <div className="text-sm text-slate-300 mt-0.5">{children}</div>}
    </div>
  </div>
);

const CertificationPanel: React.FC<{ code: string; paidReturn?: boolean }> = ({
  code,
  paidReturn,
}) => {
  const [data, setData] = useState<CertificationStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await academy.certification(code));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load certification status.');
    }
  }, [code]);

  useEffect(() => {
    void load();
  }, [load]);

  // Back from Stripe: the webhook may land a few seconds after the redirect.
  useEffect(() => {
    if (!paidReturn) return;
    let tries = 0;
    const t = window.setInterval(async () => {
      tries += 1;
      await load();
      if (tries >= 10) window.clearInterval(t);
    }, 3000);
    return () => window.clearInterval(t);
  }, [paidReturn, load]);

  if (error) {
    return (
      <div className="card p-6 mb-8">
        <p className="text-sm text-slate-300">{error}</p>
      </div>
    );
  }
  if (!data) return null;

  const { completion, advanced } = data;
  const state = advanced.state;

  return (
    <>
      {/* ---- Tier 1: Certificate of Completion ---- */}
      <section className="card p-6 mb-8" aria-labelledby="cert-completion">
        <div className="flex items-start gap-4">
          <Award className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h2 id="cert-completion" className="font-semibold text-white">
                Certificate of Completion
              </h2>
              <span className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border border-slate-600 text-slate-300">
                Included
              </span>
            </div>

            {completion.certificate ? (
              <div className="mt-4">
                <CertificateCard cert={completion.certificate} />
              </div>
            ) : completion.awaiting_name ? (
              <>
                <p className="text-sm text-slate-300 mt-1">
                  You have completed everything. Add the name to print on your certificate and
                  it will be issued immediately and emailed to you.
                </p>
                <NameForm initial={data.full_name} onSaved={() => void load()} />
              </>
            ) : (
              <>
                <p className="text-sm text-slate-300 mt-1">
                  Issued automatically the moment every lesson is complete and every module
                  evaluation and mastery check is passed. It carries a public verification
                  code and can be added to your LinkedIn profile in one click.
                </p>
                <div className="grid sm:grid-cols-2 gap-3 mt-4 text-sm">
                  <div className="rounded-lg border border-slate-700/70 bg-slate-950/40 px-4 py-3">
                    <div className="text-xs font-mono uppercase tracking-widest text-slate-400">
                      Lessons
                    </div>
                    <div className="text-white font-semibold tabular-nums mt-0.5">
                      {completion.lessons_done} of {completion.lessons_total}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-700/70 bg-slate-950/40 px-4 py-3">
                    <div className="text-xs font-mono uppercase tracking-widest text-slate-400">
                      Evaluations &amp; mastery checks passed
                    </div>
                    <div className="text-white font-semibold tabular-nums mt-0.5">
                      {completion.sets_passed} of {completion.sets_total}
                    </div>
                  </div>
                </div>
                {!data.full_name && (
                  <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
                    <p className="text-sm text-amber-200">
                      No name on file yet. Add it now so the certificate can be issued the
                      instant you finish.
                    </p>
                    <NameForm initial="" onSaved={() => void load()} />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </section>

      {/* ---- Tier 2: Certificate of Verified Competency ---- */}
      {(advanced.offered || advanced.certificate) && (
        <section className="card p-6 mb-8 border-cyan-500/30" aria-labelledby="cert-verified">
          <div className="flex items-start gap-4">
            <BadgeCheck className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h2 id="cert-verified" className="font-semibold text-white">
                  Certificate of Verified Competency
                </h2>
                <span className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300">
                  Instructor examined · {money(advanced.price_cents, advanced.currency)}
                </span>
              </div>

              {advanced.certificate ? (
                <div className="mt-4">
                  <CertificateCard cert={advanced.certificate} />
                </div>
              ) : (
                <>
                  {paidReturn && !state && (
                    <p className="mt-2 text-sm text-cyan-300 animate-pulse">
                      Confirming your payment…
                    </p>
                  )}
                  {!state && (
                    <>
                      <p className="text-sm text-slate-300 mt-1">
                        The credential a hiring manager can trust: after an advanced written
                        examination, you are examined live, one-on-one by video, for{' '}
                        {advanced.interview_minutes} minutes by the instructor. A pass issues a
                        certificate signed by the instructor attesting that you were examined in
                        person and demonstrated a verified command of{' '}
                        <span className="text-white">every key principle</span> of the subject.
                      </p>
                      <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3 mt-4">
                        <Step n={1} title="Written examination" active>
                          {advanced.exam_item_count} analysis-level questions, pass mark{' '}
                          {advanced.exam_threshold}%, {advanced.exam_max_attempts} attempts.
                        </Step>
                        <Step n={2} title="Propose your interview windows" active>
                          Three 60-minute windows in your own time zone.
                        </Step>
                        <Step n={3} title="Live oral examination" active>
                          One-on-one by video conference. Camera on, photo ID at the start.
                        </Step>
                        <Step n={4} title="Signed certificate" active>
                          Issued only by the instructor after the examination. Digitally
                          signed, publicly verifiable, LinkedIn-ready.
                        </Step>
                      </div>
                      <button
                        type="button"
                        className="btn-ghost mt-4"
                        onClick={() => setShowAll(!showAll)}
                      >
                        {showAll ? 'Hide' : 'See'} the principles examined
                      </button>
                      {showAll && (
                        <ol className="mt-2 grid sm:grid-cols-2 gap-x-6 gap-y-1 text-sm text-slate-300 list-decimal list-inside">
                          {advanced.competencies.map((c) => (
                            <li key={c}>{c}</li>
                          ))}
                        </ol>
                      )}
                      <div className="mt-5 flex flex-wrap items-center gap-3">
                        {advanced.can_purchase ? (
                          <button
                            type="button"
                            className="btn-primary"
                            disabled={busy}
                            onClick={async () => {
                              setBusy(true);
                              try {
                                const { url } = await academy.advancedCheckout(code);
                                window.location.href = url;
                              } catch (err) {
                                setError(
                                  err instanceof ApiError ? err.message : 'Could not start checkout.'
                                );
                                setBusy(false);
                              }
                            }}
                          >
                            <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                            {busy
                              ? 'Opening checkout…'
                              : `Register for the examination, ${money(advanced.price_cents, advanced.currency)}`}
                          </button>
                        ) : (
                          <p className="text-sm text-amber-200">{advanced.purchase_blocked_reason}</p>
                        )}
                      </div>
                      <p className="text-xs text-slate-500 mt-3">
                        The fee pays for the examination, not the outcome. If mastery is not
                        demonstrated at the first session, one complimentary re-examination is
                        offered after a study period; there is no refund for an unsuccessful
                        examination.
                      </p>
                    </>
                  )}

                  {state && state.status === 'purchased' && (
                    <div className="mt-3">
                      <Step n={1} title="Written examination" active>
                        {advanced.exam_item_count} questions · pass mark {advanced.exam_threshold}% ·
                        attempt {Math.min(state.exam_attempts + 1, advanced.exam_max_attempts)} of{' '}
                        {advanced.exam_max_attempts}
                        {state.exam_attempts > 0 && (
                          <> · best so far {state.exam_best_pct}%</>
                        )}
                      </Step>
                      <Link to={`/learn/advanced-exam/${code}`} className="btn-primary mt-4">
                        <ClipboardCheck className="w-4 h-4" aria-hidden="true" />
                        {state.exam_attempts > 0 ? 'Retake the written examination' : 'Start the written examination'}
                      </Link>
                    </div>
                  )}

                  {state && state.status === 'exam_failed' && (
                    <p className="mt-3 text-sm text-amber-200">
                      Both attempts at the written examination are used (best {state.exam_best_pct}%).
                      Write to info@proreadyengineer.com to discuss a further attempt.
                    </p>
                  )}

                  {state &&
                    (state.status === 'exam_passed' ||
                      state.status === 'slots_proposed' ||
                      state.status === 'retake_pending') && (
                      <div className="mt-3">
                        <Step n={2} title={state.interview_no > 1 ? 'Propose windows for your re-examination' : 'Propose your interview windows'} active>
                          {state.status === 'retake_pending' && state.retake_after && (
                            <>Your complimentary re-examination can be proposed on or after {fmtDate(state.retake_after)}. </>
                          )}
                          {state.status === 'slots_proposed' && (
                            <>Sent. Waiting for your examiner to confirm one of your windows. You will receive the meeting link by email.</>
                          )}
                        </Step>
                        {state.status === 'slots_proposed' && (
                          <ul className="mt-3 text-sm text-slate-300 space-y-1">
                            {state.proposed_slots.map((iso) => (
                              <li key={iso} className="font-mono text-xs text-slate-300">
                                {new Date(iso).toLocaleString(undefined, {
                                  dateStyle: 'full',
                                  timeStyle: 'short',
                                })}
                              </li>
                            ))}
                          </ul>
                        )}
                        {state.status === 'slots_proposed' && (
                          <p className="mt-3 text-xs text-slate-500">
                            Need different times? Send a new set below and it replaces the old one.
                          </p>
                        )}
                        {state.can_propose ? (
                          <SlotsForm
                            code={code}
                            onDone={(adv) => setData({ ...data, advanced: { ...advanced, ...adv } })}
                          />
                        ) : (
                          <p className="mt-2 text-sm text-amber-200">{state.propose_blocked_reason}</p>
                        )}
                      </div>
                    )}

                  {state && state.status === 'scheduled' && (
                    <div className="mt-3">
                      <Step n={3} title={state.interview_no > 1 ? 'Your re-examination is booked' : 'Your oral examination is booked'} active>
                        <ul className="mt-1 space-y-0.5">
                          {state.scheduled_lines.map((l) => (
                            <li key={l}>{l}</li>
                          ))}
                        </ul>
                        <p className="mt-2">
                          {advanced.interview_minutes} minutes, one-on-one by video. Join from a quiet
                          place with your camera on and have a photo ID ready. Questions are asked
                          without notice. Think aloud; the reasoning is what is examined.
                        </p>
                      </Step>
                      {state.meeting_url && (
                        <a
                          href={state.meeting_url}
                          className="btn-primary mt-4"
                          target="_blank"
                          rel="noopener"
                        >
                          <Video className="w-4 h-4" aria-hidden="true" /> Join the examination
                        </a>
                      )}
                    </div>
                  )}

                  {state && state.status === 'failed' && (
                    <p className="mt-3 text-sm text-slate-300">
                      Your examiner concluded that mastery was not demonstrated at the re-examination,
                      so no Certificate of Verified Competency was issued. Your Certificate of Completion
                      and course access are unaffected.
                    </p>
                  )}
                  {state && state.status === 'cancelled' && (
                    <p className="mt-3 text-sm text-slate-300">This examination was cancelled.</p>
                  )}
                </>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  );
};

export default CertificationPanel;
