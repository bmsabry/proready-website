import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Award,
  BookOpen,
  Check,
  ChevronRight,
  FileSpreadsheet,
  FlaskConical,
  GraduationCap,
  KeyRound,
  Lock,
  PlayCircle,
  Presentation,
  ShieldCheck,
} from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import {
  academy,
  ApiError,
  CourseState,
  formatDuration,
  LessonSummary,
  ModuleState,
} from '../../lib/academyApi';

const DEFAULT_PRODUCT = 'micro-gas-turbine-design';

const KIND_ICON: Record<LessonSummary['kind'], React.ElementType> = {
  video: PlayCircle,
  slides: Presentation,
  reading: BookOpen,
  lab: FlaskConical,
  calculator: FileSpreadsheet,
  quiz: GraduationCap,
};

const ProgressBar = ({ percent }: { percent: number }) => (
  <div
    className="h-1.5 rounded-full bg-slate-800 overflow-hidden"
    role="progressbar"
    aria-valuenow={Math.round(percent)}
    aria-valuemin={0}
    aria-valuemax={100}
  >
    <div
      className="h-full bg-gradient-to-r from-cyan-400 to-blue-500 transition-all duration-500"
      style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
    />
  </div>
);

const ModuleCard = ({ module, index }: { module: ModuleState; index: number }) => {
  const [open, setOpen] = useState(module.unlocked && module.percent < 100);
  const locked = !module.unlocked;

  return (
    <div className={`card overflow-hidden ${locked ? 'opacity-60' : ''}`}>
      <button
        type="button"
        onClick={() => !locked && setOpen((v) => !v)}
        aria-expanded={open}
        disabled={locked}
        className={`w-full flex items-start gap-4 p-5 text-left ${
          locked ? 'cursor-not-allowed' : 'hover:bg-slate-900/40'
        } transition-colors`}
      >
        <span
          className={`shrink-0 mt-0.5 w-10 h-10 rounded-xl grid place-items-center font-mono text-sm border ${
            module.percent === 100
              ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300'
              : 'bg-slate-900 border-slate-700 text-slate-400'
          }`}
        >
          {locked ? (
            <Lock className="w-4 h-4" aria-hidden="true" />
          ) : module.percent === 100 ? (
            <Check className="w-5 h-5" aria-hidden="true" />
          ) : (
            String(index + 1).padStart(2, '0')
          )}
        </span>

        <span className="flex-1 min-w-0">
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-1">
            <span className="font-mono text-xs uppercase tracking-widest text-cyan-400">
              {module.code}
            </span>
            <span className="text-xs text-slate-400">{module.hours} hrs</span>
            {module.formative_passed && (
              <span className="text-xs text-cyan-300">
                assessment passed{module.formative_score !== null ? ` · ${module.formative_score}%` : ''}
              </span>
            )}
          </span>
          <span className="block text-base font-semibold text-white leading-snug">
            {module.title}
          </span>
          {!locked && (
            <span className="block mt-3">
              <ProgressBar percent={module.percent} />
              <span className="block mt-1.5 text-xs text-slate-400">
                {module.lessons_completed} of {module.lesson_count} complete
              </span>
            </span>
          )}
          {locked && (
            <span className="block mt-2 text-xs text-slate-500">
              Clear the previous module to unlock this one.
            </span>
          )}
        </span>

        {!locked && (
          <ChevronRight
            className={`shrink-0 w-5 h-5 text-slate-500 transition-transform ${open ? 'rotate-90' : ''}`}
            aria-hidden="true"
          />
        )}
      </button>

      {open && !locked && (
        <div className="px-5 pb-5 space-y-1">
          {module.lessons.map((lesson) => {
            const Icon = KIND_ICON[lesson.kind] ?? BookOpen;
            return (
              <Link
                key={lesson.id}
                to={`/learn/lesson/${lesson.id}`}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-900/60 transition-colors group"
              >
                <Icon
                  className={`w-4 h-4 shrink-0 ${lesson.completed ? 'text-cyan-400' : 'text-slate-500'}`}
                  aria-hidden="true"
                />
                <span className="flex-1 min-w-0 text-sm text-slate-300 group-hover:text-white truncate">
                  {lesson.title}
                </span>
                {lesson.duration_s > 0 && (
                  <span className="text-xs text-slate-500 shrink-0">
                    {formatDuration(lesson.duration_s)}
                  </span>
                )}
                {lesson.completed && (
                  <Check className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
                )}
              </Link>
            );
          })}

          {module.has_formative && (
            <Link
              to={`/learn/quiz/${module.id}/formative`}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg mt-2 border transition-colors ${
                module.formative_passed
                  ? 'border-cyan-500/30 bg-cyan-500/5 hover:bg-cyan-500/10'
                  : 'border-slate-700 hover:border-cyan-500/40 hover:bg-slate-900/60'
              }`}
            >
              <GraduationCap className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
              <span className="flex-1 text-sm font-medium text-white">
                {module.formative_passed ? 'Module assessment — passed' : 'Take the module assessment'}
              </span>
              <span className="text-xs text-slate-400">
                {module.mastery_threshold}% to unlock the next
              </span>
            </Link>
          )}

          {module.quiz_app_url && (
            <a
              href={module.quiz_app_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-900/60 transition-colors"
            >
              <FlaskConical className="w-4 h-4 text-cyan-400 shrink-0" aria-hidden="true" />
              <span className="flex-1 text-sm text-slate-300">
                Open the interactive {module.code} module
              </span>
              <span className="text-xs text-slate-500">opens in a new tab</span>
            </a>
          )}
        </div>
      )}
    </div>
  );
};

/* One-time setup for the credentials the five interactive modules use.
 *
 * Those apps predate this platform and sign in with email + password, so a
 * buyer who arrived by magic link has no password to give them. Setting it
 * here rather than letting the apps offer "sign up" is deliberate: this page
 * is behind a session, which means the mailbox has already been proven, so
 * nobody can adopt a paid account by typing someone else's address. */
const SetPasswordCard: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (value.length < 8) {
      setErr('Use at least 8 characters.');
      return;
    }
    setSaving(true);
    setErr('');
    try {
      await academy.setPassword(value);
      onDone();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : 'Could not save that.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card p-6 mb-8 border-cyan-500/30">
      <div className="flex items-start gap-4">
        <KeyRound className="w-6 h-6 text-cyan-400 shrink-0 mt-0.5" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold text-white">Set a password for the interactive modules</h2>
          <p className="text-sm text-slate-300 mt-1 mb-4">
            The GT-05 to GT-15 tools open in their own apps and ask for an email
            and password. Choose one here and they'll let you straight in — the
            rest of the course stays link-based.
          </p>
          <form onSubmit={save} className="flex flex-wrap items-start gap-3">
            <input
              type="password"
              autoComplete="new-password"
              value={value}
              onChange={(ev) => setValue(ev.target.value)}
              placeholder="At least 8 characters"
              className="flex-1 min-w-[16rem] px-3 py-2 rounded-lg bg-slate-900/80 border border-slate-700 text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none"
            />
            <button type="submit" disabled={saving} className="btn-primary disabled:opacity-60">
              {saving ? 'Saving…' : 'Save password'}
            </button>
            <button type="button" onClick={onDone} className="btn-ghost">
              Later
            </button>
          </form>
          {err && (
            <p className="text-sm text-amber-300 mt-3" role="alert">
              {err}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

const Dashboard: React.FC = () => {
  const { productCode } = useParams();
  const code = productCode || DEFAULT_PRODUCT;
  const navigate = useNavigate();

  const [course, setCourse] = useState<CourseState | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState('');
  const [isOwner, setIsOwner] = useState(false);
  const [needsPassword, setNeedsPassword] = useState(false);

  usePageMeta('Your course', 'Your ProReadyEngineer course dashboard.', {
    noindex: true,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await academy.me();
        if (cancelled) return;
        if (!me.signed_in) {
          navigate('/learn/signin', { replace: true });
          return;
        }
        setEmail(me.email || '');
        setIsOwner(Boolean(me.is_owner));
        setNeedsPassword(me.has_password === false);
        const data = await academy.course(code);
        if (!cancelled) setCourse(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          navigate('/learn/signin', { replace: true });
          return;
        }
        setError(err instanceof ApiError ? err.message : 'Could not load your course.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, navigate]);

  const signOut = async () => {
    try {
      await academy.logout();
    } finally {
      navigate('/learn/signin', { replace: true });
    }
  };

  if (loading) {
    return (
      <div className="pt-40 pb-32 text-center">
        <span className="font-mono text-sm uppercase tracking-widest text-cyan-400 animate-pulse">
          Loading your course…
        </span>
      </div>
    );
  }

  if (error || !course) {
    return (
      <div className="pt-40 pb-32 container-site max-w-lg text-center">
        <div className="card p-8">
          <h1 className="text-xl font-bold mb-3">We couldn't open your course</h1>
          <p className="text-slate-300 mb-6">{error}</p>
          <Link to="/training/micro-gas-turbine-design" className="btn-secondary">
            View the course
          </Link>
        </div>
      </div>
    );
  }

  const nextLesson = course.modules
    .filter((m) => m.unlocked)
    .flatMap((m) => m.lessons)
    .find((l) => !l.completed);

  return (
    <div className="relative pt-32 pb-20">
      <div className="hero-backdrop" />
      <div className="absolute inset-0 -z-10 bg-hero-radial" />

      <div className="container-site max-w-5xl">
        <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
          <div>
            <span className="eyebrow mb-4">Your course</span>
            <h1 className="text-3xl md:text-4xl font-bold tracking-tight mt-3">
              {course.product.title}
            </h1>
            {email && (
              <p className="text-sm text-slate-400 mt-2 flex flex-wrap items-center gap-2">
                Signed in as {email}
                {isOwner && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
                    <ShieldCheck className="w-3 h-3" aria-hidden="true" /> OWNER
                  </span>
                )}
              </p>
            )}
          </div>
          <button type="button" onClick={signOut} className="btn-ghost">
            Sign out
          </button>
        </div>

        {needsPassword && <SetPasswordCard onDone={() => setNeedsPassword(false)} />}

        <div className="card p-6 mb-8">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <div>
              <div className="font-display text-3xl font-bold text-gradient tabular-nums">
                {course.percent}%
              </div>
              <div className="text-xs font-mono uppercase tracking-widest text-slate-400 mt-1">
                {course.lessons_completed} of {course.lessons_total} lessons
              </div>
            </div>
            {nextLesson && (
              <Link to={`/learn/lesson/${nextLesson.id}`} className="btn-primary">
                {course.lessons_completed === 0 ? 'Start the course' : 'Continue'}
                <ChevronRight className="w-4 h-4" aria-hidden="true" />
              </Link>
            )}
          </div>
          <ProgressBar percent={course.percent} />

          {!course.video_ready && (
            <p className="mt-4 text-sm text-amber-300/90">
              Video hosting is still being set up — lesson recordings will appear
              here shortly. Everything else is available now.
            </p>
          )}
        </div>

        {course.complete && (
          <div className="card p-6 mb-8 border-cyan-500/30">
            <div className="flex items-center gap-4">
              <Award className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
              <div className="flex-1">
                <h2 className="font-semibold text-white">You've finished the course</h2>
                <p className="text-sm text-slate-300 mt-1">
                  {course.certificate_code
                    ? `Certificate ${course.certificate_code} — verifiable at /verify/${course.certificate_code}`
                    : 'Claim your certificate.'}
                </p>
              </div>
              {!course.certificate_code && (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={async () => {
                    try {
                      const cert = await academy.certificate(code);
                      setCourse({ ...course, certificate_code: cert.code });
                    } catch {
                      /* the dashboard already shows completion state */
                    }
                  }}
                >
                  Get certificate
                </button>
              )}
            </div>
          </div>
        )}

        <div className="space-y-4">
          {course.modules.map((m, i) => (
            <ModuleCard key={m.id} module={m} index={i} />
          ))}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
