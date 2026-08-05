import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Check, Download, ExternalLink } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import { academy, ApiError, LessonDetail } from '../../lib/academyApi';

/* Lesson player.
 *
 * Video is served by Cloudflare Stream through a signed, short-lived URL that
 * the API only mints after checking entitlement, so there is no public URL to
 * share. The iframe player has downloads disabled server-side; the watermark
 * over it carries the learner's own email, which is the part that actually
 * deters redistribution once a recording leaves the building.
 *
 * Progress is reported on a 15s heartbeat rather than continuously. The API
 * clamps each beat to 60s of credit, so a tab left open in the background
 * cannot fabricate completion. */

const HEARTBEAT_MS = 15000;

const Watermark = ({ text }: { text: string }) =>
  text ? (
    <div
      className="pointer-events-none absolute inset-0 z-10 overflow-hidden select-none"
      aria-hidden="true"
    >
      <span className="absolute top-3 right-4 text-[11px] font-mono text-white/35 drop-shadow">
        {text}
      </span>
      <span className="absolute bottom-3 left-4 text-[11px] font-mono text-white/25 drop-shadow">
        {text}
      </span>
    </div>
  ) : null;

const Lesson: React.FC = () => {
  const { lessonId } = useParams();
  const navigate = useNavigate();
  const id = Number(lessonId);

  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [completed, setCompleted] = useState(false);

  const lastBeat = useRef<number>(Date.now());

  usePageMeta(lesson?.title || 'Lesson', 'ProReadyEngineer course lesson.', {
    noindex: true,
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    (async () => {
      try {
        const data = await academy.lesson(id);
        if (cancelled) return;
        setLesson(data);
        setCompleted(data.progress.completed);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          navigate('/learn/signin', { replace: true });
          return;
        }
        setError(err instanceof ApiError ? err.message : 'Could not open this lesson.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, navigate]);

  const beat = useCallback(async () => {
    if (!lesson || lesson.is_preview) return;
    const now = Date.now();
    const delta = Math.round((now - lastBeat.current) / 1000);
    lastBeat.current = now;
    if (delta <= 0) return;
    try {
      const res = await academy.heartbeat(lesson.id, lesson.progress.position_s + delta, delta);
      if (res.completed) setCompleted(true);
    } catch {
      /* a dropped beat is not worth interrupting the lesson for */
    }
  }, [lesson]);

  useEffect(() => {
    if (!lesson) return;
    lastBeat.current = Date.now();
    const timer = window.setInterval(() => {
      // Only credit time while the tab is actually in front of the learner.
      if (document.visibilityState === 'visible') beat();
      else lastBeat.current = Date.now();
    }, HEARTBEAT_MS);
    return () => window.clearInterval(timer);
  }, [lesson, beat]);

  if (loading) {
    return (
      <div className="pt-40 pb-32 text-center">
        <span className="font-mono text-sm uppercase tracking-widest text-cyan-400 animate-pulse">
          Loading lesson…
        </span>
      </div>
    );
  }

  if (error || !lesson) {
    return (
      <div className="pt-40 pb-32 container-site max-w-lg text-center">
        <div className="card p-8">
          <h1 className="text-xl font-bold mb-3">This lesson isn't available</h1>
          <p className="text-slate-300 mb-6">{error}</p>
          <Link to="/learn" className="btn-secondary">
            Back to your course
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="relative pt-28 pb-20">
      <div className="absolute inset-0 -z-10 bg-hero-radial" />
      <div className="container-site max-w-4xl">
        <Link to="/learn" className="btn-ghost mb-6">
          <ArrowLeft className="w-4 h-4" aria-hidden="true" />
          {lesson.module.code} — {lesson.module.title}
        </Link>

        <h1 className="text-2xl md:text-3xl font-bold tracking-tight mb-6">{lesson.title}</h1>

        {lesson.kind === 'video' && (
          <div className="relative rounded-xl overflow-hidden border border-slate-800 bg-black aspect-video mb-6">
            {lesson.playback ? (
              <>
                <iframe
                  src={lesson.playback.iframe}
                  title={lesson.title}
                  allow="accelerometer; gyroscope; encrypted-media; picture-in-picture;"
                  allowFullScreen
                  className="w-full h-full"
                />
                <Watermark text={lesson.watermark} />
              </>
            ) : (
              <div className="w-full h-full grid place-items-center text-center px-6">
                <div>
                  <p className="text-slate-300 font-medium">This recording is being prepared.</p>
                  <p className="text-sm text-slate-500 mt-2">
                    The lecture will appear here as soon as it finishes processing.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        {(lesson.kind === 'slides' || lesson.kind === 'calculator') && (
          <div className="card p-6 mb-6 relative overflow-hidden">
            <Watermark text={lesson.watermark} />
            <p className="text-slate-300 leading-relaxed">
              {lesson.kind === 'slides'
                ? 'The deck for this session opens in the viewer below.'
                : 'The design spreadsheet for this session.'}
            </p>
            {lesson.asset_path && (
              <a
                href={lesson.asset_path}
                className="btn-secondary mt-4"
                target="_blank"
                rel="noopener noreferrer"
              >
                Open <ExternalLink className="w-4 h-4" aria-hidden="true" />
              </a>
            )}
          </div>
        )}

        {lesson.kind === 'lab' && lesson.asset_path && (
          <div className="card p-6 mb-6">
            <p className="text-slate-300 leading-relaxed mb-4">
              This interactive tool runs in its own window so it has room to work.
            </p>
            <a
              href={lesson.asset_path}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary"
            >
              Launch the tool <ExternalLink className="w-4 h-4" aria-hidden="true" />
            </a>
          </div>
        )}

        {lesson.kind === 'quiz' && lesson.asset_path && (
          <div className="card p-6 mb-6">
            <p className="text-slate-300 leading-relaxed mb-4">
              The interactive assessment for this module opens in a new tab. Your
              account carries across — no separate sign-in.
            </p>
            <a
              href={lesson.asset_path}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary"
            >
              Open the assessment <ExternalLink className="w-4 h-4" aria-hidden="true" />
            </a>
          </div>
        )}

        {lesson.body && (
          <div className="prose-dark card p-6 mb-6">
            <p className="whitespace-pre-wrap">{lesson.body}</p>
          </div>
        )}

        <div className="flex items-center justify-between gap-4 pt-4 border-t border-slate-800">
          <div className="text-sm">
            {completed ? (
              <span className="inline-flex items-center gap-2 text-cyan-400">
                <Check className="w-4 h-4" aria-hidden="true" /> Complete
              </span>
            ) : (
              <span className="text-slate-500">Progress saves as you go</span>
            )}
          </div>
          <div className="flex gap-3">
            {lesson.prev_lesson_id && (
              <Link to={`/learn/lesson/${lesson.prev_lesson_id}`} className="btn-secondary">
                <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Previous
              </Link>
            )}
            {lesson.next_lesson_id && (
              <Link to={`/learn/lesson/${lesson.next_lesson_id}`} className="btn-primary">
                Next <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </Link>
            )}
          </div>
        </div>

        <p className="mt-8 text-xs text-slate-600 flex items-center gap-2">
          <Download className="w-3.5 h-3.5" aria-hidden="true" />
          Lecture recordings stream only and are not downloadable. This copy is
          registered to {lesson.watermark || 'your account'}.
        </p>
      </div>
    </div>
  );
};

export default Lesson;
