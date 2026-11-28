import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Check, ShieldCheck, X } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import { useAnswerDraft } from '../../lib/useAnswerDraft';
import {
  academy,
  AdvancedExamResult,
  AdvancedExamSet,
  ApiError,
} from '../../lib/academyApi';

/* The written examination of the instructor-examined tier.
 *
 * Deliberately sparser than the module quiz: no explanations after
 * submission (the bank must stay examinable for the second attempt and the
 * oral examination), a visible attempt counter, and a single confirmation
 * before the paper is handed in. */

const AdvancedExam: React.FC = () => {
  const { productCode = '' } = useParams();
  const navigate = useNavigate();
  const [exam, setExam] = useState<AdvancedExamSet | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<AdvancedExamResult | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [confirm, setConfirm] = useState(false);
  // Autosave to the server: what was last sent, when it was stored, and
  // whether the last try worked. The page says plainly when it did not.
  const [saved, setSaved] = useState<{ at: string | null; count: number }>({ at: null, count: 0 });
  const [saveTrouble, setSaveTrouble] = useState<'' | 'offline' | 'signed_out' | 'closed'>('');
  const [retryTick, setRetryTick] = useState(0);
  const lastSent = useRef<string>('{}');

  usePageMeta('Written examination', 'ProReadyEngineer advanced written examination.', {
    noindex: true,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [data, me] = await Promise.all([
          academy.advancedExam(productCode),
          academy.me().catch(() => null),
        ]);
        if (cancelled) return;
        // The Training Terms are accepted on the course page; the examination
        // opened from a link must not skip them.
        if (me?.signed_in && me.terms_version && !me.terms_accepted && !me.is_owner) {
          navigate(`/learn/${productCode}`, { replace: true });
          return;
        }
        // Answers saved on the site for this paper come back first; a copy
        // kept by this browser tab (useAnswerDraft) is laid over them.
        const draft = data.draft ?? {};
        if (Object.keys(draft).length > 0) {
          setAnswers(draft);
          lastSent.current = JSON.stringify(draft);
        }
        setSaved({ at: data.draft_saved_at ?? null, count: Object.keys(draft).length });
        setExam(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          // Sign in, then come straight back to the examination.
          navigate(
            `/learn/signin?next=${encodeURIComponent(`/learn/advanced-exam/${productCode}`)}`,
            { replace: true },
          );
          return;
        }
        setError(err instanceof ApiError ? err.message : 'Could not load the examination.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [productCode, navigate]);

  const total = exam?.items.length ?? 0;
  const answered = Object.keys(answers).filter(
    (k) => answers[k] !== undefined && answers[k] !== ''
  ).length;

  // One hundred answers must not be lost to a reload or a discarded tab. The
  // key names this exact paper, so answers to an earlier paper are never
  // restored onto a new one.
  useAnswerDraft(
    exam && exam.items.length > 0
      ? `pre:draft:exam:${productCode}:${exam.items[0].code}:${exam.items[exam.items.length - 1].code}:${exam.items.length}`
      : null,
    exam ? exam.items.map((item) => item.code) : [],
    answers,
    (restored) => setAnswers((current) => ({ ...current, ...restored })),
    result !== null,
  );

  // Save the answers on the site a few seconds after each change, and again
  // when the page is hidden or closed. A hand-in that never arrives (a
  // dropped connection, an expired sign-in, a closed tab) then loses nothing,
  // and the instructor can see what was answered.
  const saveNow = useCallback(
    async (keepalive = false) => {
      if (!exam || result) return;
      const body = JSON.stringify(answers);
      if (body === lastSent.current) return;
      try {
        const r = await academy.saveAdvancedExamDraft(productCode, answers, keepalive);
        lastSent.current = body;
        setSaved({ at: r.saved_at, count: r.answered });
        setSaveTrouble('');
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) setSaveTrouble('signed_out');
        else if (err instanceof ApiError && err.status === 409) setSaveTrouble('closed');
        else setSaveTrouble('offline');
      }
    },
    [exam, result, answers, productCode],
  );

  useEffect(() => {
    const t = window.setTimeout(() => void saveNow(), 2500);
    return () => window.clearTimeout(t);
  }, [saveNow, retryTick]);

  useEffect(() => {
    if (!saveTrouble || saveTrouble === 'closed') return;
    const t = window.setInterval(() => setRetryTick((n) => n + 1), 20000);
    return () => window.clearInterval(t);
  }, [saveTrouble]);

  useEffect(() => {
    const flush = () => {
      if (document.visibilityState === 'hidden') void saveNow(true);
    };
    const onHide = () => void saveNow(true);
    document.addEventListener('visibilitychange', flush);
    window.addEventListener('pagehide', onHide);
    return () => {
      document.removeEventListener('visibilitychange', flush);
      window.removeEventListener('pagehide', onHide);
    };
  }, [saveNow]);

  const savedClock = saved.at
    ? new Date(saved.at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : '';

  const submit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const res = await academy.submitAdvancedExam(productCode, answers);
      setResult(res);
      setConfirm(false);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      // Say in so many words that nothing was handed in, keep the answers,
      // and leave the Submit button where it is for the next try.
      if (err instanceof ApiError && err.status === 401) {
        setError(
          'You are signed out. Your answers are kept on this page. Sign in using the link below (it opens a new tab), then come back to this tab and press Submit for grading again.',
        );
        setSaveTrouble('signed_out');
      } else if (err instanceof ApiError && err.status !== 0) {
        setError(err.message);
      } else {
        setError(
          `The site could not be reached. Your answers are kept on this page${
            savedClock ? ` and saved on the site as of ${savedClock}` : ''
          }. Check your connection and press Submit for grading again.`,
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="pt-40 pb-32 text-center">
        <span className="font-mono text-sm uppercase tracking-widest text-cyan-400 animate-pulse">
          Loading examination…
        </span>
      </div>
    );
  }

  if (error && !exam) {
    return (
      <div className="pt-40 pb-32 container-site max-w-lg text-center">
        <div className="card p-8">
          <h1 className="text-xl font-bold mb-3">Examination unavailable</h1>
          <p className="text-slate-300 mb-6">{error}</p>
          <Link to={`/learn/${productCode}`} className="btn-secondary">
            Back to your course
          </Link>
        </div>
      </div>
    );
  }
  if (!exam) return null;

  const verdict = (code: string) => result?.feedback.find((f) => f.code === code);

  return (
    <div className="relative pt-28 pb-20">
      <div className="hero-backdrop" />
      <div className="container-site max-w-3xl">
        <Link to={`/learn/${productCode}`} className="btn-ghost mb-6">
          <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Back to your course
        </Link>

        <div className="mb-8">
          <span className="eyebrow">Instructor-examined certification · written examination</span>
          <h1 className="text-3xl font-bold tracking-tight mt-3">{exam.product.title}</h1>
          <p className="text-slate-300 mt-2">
            {total} questions at analysis level. Pass mark {exam.threshold}%. Attempt{' '}
            {Math.min(exam.attempts_used + 1, exam.attempts_max)} of {exam.attempts_max}. Answers
            are graded on submission; no explanations are shown, so the bank stays examinable for
            the oral examination.
          </p>
          {!result && (
            <p className="text-xs text-slate-400 mt-3">
              Your answers are saved on the site as you work, so a reload, a closed tab or another
              device does not lose them. The paper is only graded when you press{' '}
              <strong className="text-slate-200">Submit for grading</strong> and see your score.
            </p>
          )}
        </div>

        {result && (
          <div
            className={`card p-6 mb-8 ${result.passed ? 'border-cyan-500/40' : 'border-amber-500/40'}`}
          >
            <div className="flex items-center gap-4">
              {result.passed ? (
                <ShieldCheck className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
              ) : (
                <X className="w-8 h-8 text-amber-400 shrink-0" aria-hidden="true" />
              )}
              <div className="flex-1">
                <h2 className="font-semibold text-white">
                  {result.passed
                    ? `Passed with ${result.score_pct}%`
                    : `Not yet: ${result.score_pct}% (pass mark ${result.threshold}%)`}
                </h2>
                <p className="text-sm text-slate-300 mt-1">
                  {result.auto_correct} of {result.auto_total} correct.{' '}
                  {result.passed
                    ? 'Next: propose your interview windows from your course page.'
                    : result.status === 'exam_failed'
                    ? 'Both attempts are used. Write to info@proreadyengineer.com to discuss a further attempt.'
                    : `You have ${result.attempts_max - result.attempts_used} attempt left. Review the material before retaking.`}{' '}
                  Your result has also been emailed to you.
                </p>
              </div>
              <Link to={`/learn/${productCode}`} className="btn-primary">
                Back to your course
              </Link>
            </div>
          </div>
        )}

        <div className="space-y-5">
          {exam.items.map((item, idx) => {
            const v = verdict(item.code);
            return (
              <div
                key={item.code}
                className={`card p-5 ${
                  v?.correct === true
                    ? 'border-cyan-500/30'
                    : v?.correct === false
                    ? 'border-amber-500/30'
                    : ''
                }`}
              >
                <div className="flex items-start gap-3 mb-4">
                  <span className="shrink-0 font-mono text-xs text-slate-500 mt-1">{idx + 1}</span>
                  <p className="flex-1 text-white leading-relaxed">{item.stem}</p>
                  {v?.correct === true && (
                    <Check className="w-5 h-5 text-cyan-400 shrink-0" aria-hidden="true" />
                  )}
                  {v?.correct === false && (
                    <X className="w-5 h-5 text-amber-400 shrink-0" aria-hidden="true" />
                  )}
                </div>
                {item.kind === 'mcq' && (
                  <div className="space-y-2 pl-7">
                    {item.options.map((opt) => (
                      <label
                        key={opt.key}
                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                          answers[item.code] === opt.key
                            ? 'border-cyan-500/50 bg-cyan-500/5'
                            : 'border-slate-800 hover:border-slate-600'
                        } ${result ? 'cursor-default' : ''}`}
                      >
                        <input
                          type="radio"
                          name={item.code}
                          value={opt.key}
                          disabled={!!result}
                          checked={answers[item.code] === opt.key}
                          onChange={() => setAnswers((a) => ({ ...a, [item.code]: opt.key }))}
                          className="mt-1 accent-cyan-400"
                        />
                        <span className="text-sm text-slate-300">
                          <span className="font-mono text-slate-500 mr-2">{opt.key}</span>
                          {opt.text}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
                {item.kind === 'numeric' && (
                  <div className="pl-7">
                    <input
                      type="text"
                      inputMode="decimal"
                      disabled={!!result}
                      value={(answers[item.code] as string) ?? ''}
                      onChange={(e) => setAnswers((a) => ({ ...a, [item.code]: e.target.value }))}
                      placeholder="Your value"
                      className="w-full max-w-xs px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none"
                    />
                    <p className="text-xs text-slate-500 mt-2">Units are fine; we read the number.</p>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {!result && (
          <div className="card p-6 mt-8 flex flex-wrap items-center justify-between gap-4">
            <div className="text-sm text-slate-300">
              {/* Each changing piece of text sits in its own element: a page
                  translated in the browser crashed here when the last
                  question was answered and this sentence disappeared. */}
              <span>{answered}</span> of <span>{total}</span> answered
              {answered < total && <span>. Unanswered questions count as incorrect.</span>}
              <div className="text-xs mt-1">
                {saveTrouble === 'signed_out' ? (
                  <span className="text-red-300">
                    Not saving: you are signed out.{' '}
                    <a
                      href={`/learn/signin?next=${encodeURIComponent(`/learn/advanced-exam/${productCode}`)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="underline"
                    >
                      Sign in in a new tab
                    </a>
                    , then come back here.
                  </span>
                ) : saveTrouble === 'offline' ? (
                  <span className="text-amber-300">
                    Not saving: the site cannot be reached. Your answers stay on this page; saving
                    resumes when the connection is back.
                  </span>
                ) : saveTrouble === 'closed' ? (
                  <span className="text-amber-300">
                    This paper is no longer open. Go back to your course page to see where you stand.
                  </span>
                ) : savedClock ? (
                  <span className="text-slate-400">
                    Saved on the site at {savedClock} ({saved.count} answered). Not handed in yet.
                  </span>
                ) : (
                  <span className="text-slate-400">Not handed in yet.</span>
                )}
              </div>
            </div>
            {!confirm ? (
              <button type="button" className="btn-primary" onClick={() => setConfirm(true)}>
                Hand in the paper
              </button>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm text-amber-200">
                  Not handed in until you press Submit for grading. This uses attempt{' '}
                  {Math.min(exam.attempts_used + 1, exam.attempts_max)} of {exam.attempts_max}.
                </span>
                <button type="button" className="btn-secondary" onClick={() => setConfirm(false)}>
                  Keep working
                </button>
                <button type="button" className="btn-primary" onClick={submit} disabled={submitting}>
                  {submitting ? 'Grading…' : 'Submit for grading'}
                </button>
              </div>
            )}
            {error && (
              <div className="basis-full text-sm text-red-200 bg-red-950/50 border border-red-800/70 rounded-lg px-4 py-3">
                <strong className="block mb-1">This hand-in did not go through.</strong>
                {error}
                {saveTrouble === 'signed_out' && (
                  <div className="mt-2">
                    <a
                      href={`/learn/signin?next=${encodeURIComponent(`/learn/advanced-exam/${productCode}`)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="underline text-red-100"
                    >
                      Open the sign-in page in a new tab
                    </a>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default AdvancedExam;
