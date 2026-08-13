import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Check, Download, ExternalLink } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import {
  academy,
  ApiError,
  LessonDetail,
  lessonAssetUrl,
  slideImageUrl,
} from '../../lib/academyApi';

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

/* In-browser deck viewer. The pixels come from the entitlement-checked,
 * per-learner-watermarked endpoint — there is no file to download, which is
 * the whole protection model for course materials. crossOrigin with
 * credentials is what lets the <img> carry the session cookie to the API. */
const SlideViewer = ({ lesson }: { lesson: LessonDetail }) => {
  const [index, setIndex] = useState(0);
  const slides = lesson.slides;
  const moduleId = lesson.module.id as number;
  const current = slides[index];
  const stripRef = useRef<HTMLDivElement>(null);

  const go = useCallback(
    (delta: number) =>
      setIndex((i) => Math.min(slides.length - 1, Math.max(0, i + delta))),
    [slides.length]
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'PageDown') go(1);
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go]);

  useEffect(() => {
    // Keep the active thumbnail in view as the learner pages through.
    const strip = stripRef.current;
    const active = strip?.querySelector<HTMLElement>(`[data-slide="${index}"]`);
    active?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  }, [index]);

  if (!slides.length || moduleId == null) return null;

  return (
    <div
      className="mb-6 select-none"
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="relative rounded-xl overflow-hidden border border-slate-800 bg-black">
        <img
          key={current.number}
          src={slideImageUrl(moduleId, current.number, 'lg')}
          crossOrigin="use-credentials"
          draggable={false}
          alt={current.title || `Slide ${current.number}`}
          className="w-full h-auto block"
        />
        <Watermark text={lesson.watermark} />
        {/* Click zones: left third back, rest forward. */}
        <button
          type="button"
          aria-label="Previous slide"
          onClick={() => go(-1)}
          className="absolute inset-y-0 left-0 w-1/3 cursor-w-resize opacity-0"
        />
        <button
          type="button"
          aria-label="Next slide"
          onClick={() => go(1)}
          className="absolute inset-y-0 right-0 w-2/3 cursor-e-resize opacity-0"
        />
      </div>

      <div className="flex items-center justify-between gap-3 mt-3">
        <button type="button" onClick={() => go(-1)} disabled={index === 0}
          className="btn-secondary disabled:opacity-40">
          <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Prev
        </button>
        <div className="text-sm text-slate-400 font-mono">
          {index + 1} / {slides.length}
          {current.section ? (
            <span className="ml-3 text-slate-500 hidden sm:inline">{current.section}</span>
          ) : null}
        </div>
        <button type="button" onClick={() => go(1)} disabled={index === slides.length - 1}
          className="btn-secondary disabled:opacity-40">
          Next <ArrowRight className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      <div
        ref={stripRef}
        className="mt-3 flex gap-2 overflow-x-auto pb-2"
        aria-label="Slide thumbnails"
      >
        {slides.map((s, i) => (
          <button
            key={s.number}
            type="button"
            data-slide={i}
            onClick={() => setIndex(i)}
            className={`shrink-0 rounded border ${
              i === index ? 'border-cyan-400' : 'border-slate-800 opacity-60 hover:opacity-100'
            }`}
            title={s.title || `Slide ${s.number}`}
          >
            <img
              src={slideImageUrl(moduleId, s.number, 'sm')}
              crossOrigin="use-credentials"
              draggable={false}
              loading="lazy"
              alt=""
              className="h-14 w-auto block rounded"
            />
          </button>
        ))}
      </div>
    </div>
  );
};

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
        <Link
          to={lesson.module.product_code ? `/learn/${lesson.module.product_code}` : '/learn'}
          className="btn-ghost mb-6"
        >
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

        {lesson.kind === 'slides' &&
          (lesson.slides.length > 0 ? (
            <SlideViewer lesson={lesson} />
          ) : (
            <div className="card p-6 mb-6 relative overflow-hidden">
              <Watermark text={lesson.watermark} />
              <p className="text-slate-300 leading-relaxed">
                The deck for this session is being prepared and will appear here
                shortly.
              </p>
              {lesson.asset_path && !lesson.asset_path.startsWith('blob:') && (
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
          ))}

        {lesson.kind === 'calculator' && (
          <div className="card p-6 mb-6 relative overflow-hidden">
            <Watermark text={lesson.watermark} />
            <p className="text-slate-300 leading-relaxed">
              The design spreadsheet for this session.
            </p>
            {lesson.asset_path && (
              <a
                href={
                  lesson.asset_path.startsWith('blob:')
                    ? lessonAssetUrl(lesson.id)
                    : lesson.asset_path
                }
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
            <p className="text-slate-300 leading-relaxed mb-2">
              This interactive tool runs in its own window so it has room to work.
            </p>
            <p className="text-xs text-slate-500 mb-4">
              Training simulation only — generic behavior, not any specific
              engine. Never apply values from it to real equipment. Your access
              is personal and watermarked with your account email.
            </p>
            <a
              href={
                lesson.asset_path.startsWith('blob:')
                  ? lessonAssetUrl(lesson.id)
                  : lesson.asset_path
              }
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
          Course materials are view-only and are not downloadable. This copy is
          registered to {lesson.watermark || 'your account'} — for training use
          only, never for operation of real equipment.
        </p>
      </div>
    </div>
  );
};

export default Lesson;
