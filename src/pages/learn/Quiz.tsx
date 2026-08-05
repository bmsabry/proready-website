import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Check, RotateCcw, X } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import { academy, ApiError, QuizItem, QuizResult, QuizSet } from '../../lib/academyApi';

/* Module assessment runner.
 *
 * The answer key never reaches this component — the API strips it — so every
 * verdict here comes from the server's grading response after submission.
 * Items carry a `section` derived from the curriculum spine, which is what
 * lets a 41-item bank be presented as a handful of readable groups rather
 * than one intimidating wall. */

const Quiz: React.FC = () => {
  const { moduleId, itemSet } = useParams();
  const navigate = useNavigate();
  const id = Number(moduleId);
  const set = (itemSet === 'summative' ? 'summative' : 'formative') as
    | 'formative'
    | 'summative';

  const [quiz, setQuiz] = useState<QuizSet | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  usePageMeta('Module assessment', 'ProReadyEngineer module assessment.', {
    noindex: true,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await academy.quiz(id, set);
        if (!cancelled) setQuiz(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          navigate('/learn/signin', { replace: true });
          return;
        }
        setError(err instanceof ApiError ? err.message : 'Could not load the assessment.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, set, navigate]);

  const sections = useMemo(() => {
    if (!quiz) return [];
    const bySection = new Map<number, QuizItem[]>();
    quiz.items.forEach((item) => {
      const list = bySection.get(item.section) ?? [];
      list.push(item);
      bySection.set(item.section, list);
    });
    return [...bySection.entries()].sort((a, b) => a[0] - b[0]);
  }, [quiz]);

  const answered = Object.keys(answers).filter(
    (k) => answers[k] !== undefined && answers[k] !== ''
  ).length;
  const total = quiz?.items.length ?? 0;

  const submit = async () => {
    if (!quiz) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await academy.submitQuiz(id, set, answers);
      setResult(res);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not submit.');
    } finally {
      setSubmitting(false);
    }
  };

  const retake = () => {
    setResult(null);
    setAnswers({});
    window.scrollTo({ top: 0 });
  };

  if (loading) {
    return (
      <div className="pt-40 pb-32 text-center">
        <span className="font-mono text-sm uppercase tracking-widest text-cyan-400 animate-pulse">
          Loading assessment…
        </span>
      </div>
    );
  }

  if (error && !quiz) {
    return (
      <div className="pt-40 pb-32 container-site max-w-lg text-center">
        <div className="card p-8">
          <h1 className="text-xl font-bold mb-3">Assessment unavailable</h1>
          <p className="text-slate-300 mb-6">{error}</p>
          <Link to="/learn" className="btn-secondary">
            Back to your course
          </Link>
        </div>
      </div>
    );
  }

  if (!quiz) return null;

  const verdictFor = (code: string) =>
    result?.feedback.find((f) => f.code === code);

  return (
    <div className="relative pt-28 pb-24">
      <div className="absolute inset-0 -z-10 bg-hero-radial" />
      <div className="container-site max-w-3xl">
        <Link to="/learn" className="btn-ghost mb-6">
          <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Back to your course
        </Link>

        <span className="eyebrow mb-4">
          {quiz.module.code} · {set === 'formative' ? 'Module check' : 'Summative'}
        </span>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight mt-3 mb-2">
          {quiz.module.title}
        </h1>
        <p className="text-slate-400 mb-8">
          {total} questions · {quiz.threshold}% to clear this module
        </p>

        {result && (
          <div
            className={`card p-6 mb-8 ${
              result.passed ? 'border-cyan-500/40' : 'border-amber-500/40'
            }`}
          >
            <div className="flex items-center gap-4">
              <div className="font-display text-4xl font-bold tabular-nums text-gradient">
                {result.score_pct}%
              </div>
              <div className="flex-1">
                <h2 className="font-semibold text-white">
                  {result.passed ? 'Passed — next module unlocked' : 'Not quite yet'}
                </h2>
                <p className="text-sm text-slate-300 mt-1">
                  {result.auto_correct} of {result.auto_total} correct
                  {result.passed
                    ? '. Your progress is saved.'
                    : `. You need ${result.threshold}% — review the explanations below and try again.`}
                </p>
              </div>
              {result.passed ? (
                <Link to="/learn" className="btn-primary">
                  Continue
                </Link>
              ) : (
                <button type="button" onClick={retake} className="btn-secondary">
                  <RotateCcw className="w-4 h-4" aria-hidden="true" /> Retake
                </button>
              )}
            </div>
          </div>
        )}

        {sections.map(([sectionNo, items]) => (
          <div key={sectionNo} className="mb-10">
            {sections.length > 1 && (
              <h2 className="text-xs font-mono uppercase tracking-widest text-slate-500 mb-4">
                Part {sectionNo}
              </h2>
            )}
            <div className="space-y-5">
              {items.map((item, idx) => {
                const v = verdictFor(item.code);
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
                      <span className="shrink-0 font-mono text-xs text-slate-500 mt-1">
                        {idx + 1}
                      </span>
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
                              onChange={() =>
                                setAnswers((a) => ({ ...a, [item.code]: opt.key }))
                              }
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
                          onChange={(e) =>
                            setAnswers((a) => ({ ...a, [item.code]: e.target.value }))
                          }
                          placeholder="e.g. 335 m/s"
                          className="w-full max-w-xs px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none"
                        />
                        <p className="text-xs text-slate-500 mt-2">
                          Units are fine — we read the number.
                        </p>
                      </div>
                    )}

                    {item.kind === 'short' && (
                      <div className="pl-7">
                        <textarea
                          rows={4}
                          disabled={!!result}
                          value={(answers[item.code] as string) ?? ''}
                          onChange={(e) =>
                            setAnswers((a) => ({ ...a, [item.code]: e.target.value }))
                          }
                          className="w-full px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white focus:border-cyan-500 focus:outline-none"
                        />
                        {item.rubric && (
                          <details className="mt-2">
                            <summary className="text-xs text-cyan-400 cursor-pointer">
                              What this is marked against
                            </summary>
                            <p className="text-xs text-slate-400 mt-2 whitespace-pre-wrap">
                              {item.rubric}
                            </p>
                          </details>
                        )}
                      </div>
                    )}

                    {v && (v.explanation || v.needs_review) && (
                      <div className="mt-4 ml-7 pl-4 border-l-2 border-slate-700">
                        {v.needs_review ? (
                          <p className="text-sm text-slate-400">
                            Held for review — written answers are marked against the
                            rubric and don't count against your score.
                          </p>
                        ) : (
                          <p className="text-sm text-slate-400">{v.explanation}</p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {!result && (
          <div className="sticky bottom-4 card p-4 flex items-center justify-between gap-4 backdrop-blur">
            <span className="text-sm text-slate-400">
              {answered} of {total} answered
            </span>
            {error && (
              <span className="text-sm text-amber-300" role="alert">
                {error}
              </span>
            )}
            <button
              type="button"
              onClick={submit}
              disabled={submitting || answered === 0}
              className="btn-primary disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {submitting ? 'Marking…' : 'Submit assessment'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default Quiz;
