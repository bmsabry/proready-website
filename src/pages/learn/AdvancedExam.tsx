import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Check, ShieldCheck, X } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
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

  usePageMeta('Written examination', 'ProReadyEngineer advanced written examination.', {
    noindex: true,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await academy.advancedExam(productCode);
        if (!cancelled) setExam(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          navigate('/learn/signin', { replace: true });
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

  const submit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const res = await academy.submitAdvancedExam(productCode, answers);
      setResult(res);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not submit.');
    } finally {
      setSubmitting(false);
      setConfirm(false);
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
            are graded on submission; no explanations are shown — the bank stays examinable for
            the oral examination.
          </p>
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
                    ? `Passed — ${result.score_pct}%`
                    : `Not yet — ${result.score_pct}% (pass mark ${result.threshold}%)`}
                </h2>
                <p className="text-sm text-slate-300 mt-1">
                  {result.auto_correct} of {result.auto_total} correct.{' '}
                  {result.passed
                    ? 'Next: propose your interview windows from your course page.'
                    : result.status === 'exam_failed'
                    ? 'Both attempts are used. Write to info@proreadyengineer.com to discuss a further attempt.'
                    : `You have ${result.attempts_max - result.attempts_used} attempt left. Review the material before retaking.`}
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
                    <p className="text-xs text-slate-500 mt-2">Units are fine — we read the number.</p>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {!result && (
          <div className="card p-6 mt-8 flex flex-wrap items-center justify-between gap-4">
            <div className="text-sm text-slate-300">
              {answered} of {total} answered
              {answered < total && ' — unanswered questions count as incorrect.'}
            </div>
            {!confirm ? (
              <button type="button" className="btn-primary" onClick={() => setConfirm(true)}>
                Hand in the paper
              </button>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm text-amber-200">
                  This uses attempt {Math.min(exam.attempts_used + 1, exam.attempts_max)} of{' '}
                  {exam.attempts_max}.
                </span>
                <button type="button" className="btn-secondary" onClick={() => setConfirm(false)}>
                  Keep working
                </button>
                <button type="button" className="btn-primary" onClick={submit} disabled={submitting}>
                  {submitting ? 'Grading…' : 'Submit for grading'}
                </button>
              </div>
            )}
            {error && <p className="text-sm text-red-300 basis-full">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
};

export default AdvancedExam;
