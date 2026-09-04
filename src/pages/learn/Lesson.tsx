import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  ExternalLink,
  Loader2,
  Maximize2,
  Minimize2,
  Play,
  X,
} from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import {
  academy,
  ApiError,
  GateBlock,
  LessonDetail,
  lessonAssetUrl,
  slideImageUrl,
  slideVideoUrl,
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
      {/* Centered above the deck's footer band — the bottom-left corner
          collided with the slides' own footer text. */}
      <span className="absolute bottom-[13%] left-1/2 -translate-x-1/2 text-[11px] font-mono text-white/25 drop-shadow">
        {text}
      </span>
    </div>
  ) : null;

const fmt = (s: number) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`;
};

/* Chapter navigation over the Stream iframe.
 *
 * A three-and-a-half-hour lecture is unusable without it: the chapters come
 * from matching what was on screen to the deck's own section structure, so
 * they mark where a topic is genuinely taught rather than where a file
 * happened to be cut.
 *
 * Seeking uses Cloudflare's player SDK, which drives the existing iframe in
 * place. If the script is blocked — corporate proxy, offline, an adblocker
 * that dislikes the domain — the click falls back to reloading the iframe at
 * ?startTime=, which is slower but always works. Never leave the learner with
 * a chapter list that silently does nothing. */
const STREAM_SDK = 'https://embed.cloudflarestream.com/embed/sdk.latest.js';

const useStreamPlayer = (
  iframeRef: React.RefObject<HTMLIFrameElement>,
  enabled: boolean
) => {
  const playerRef = useRef<any>(null);
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    const frame = iframeRef.current;

    const attach = () => {
      const w = window as any;
      const el = iframeRef.current;
      if (cancelled || !w.Stream || !el) return;
      try {
        const player = w.Stream(el);
        playerRef.current = player;
        player.addEventListener('timeupdate', () =>
          setCurrent(player.currentTime || 0)
        );
      } catch {
        playerRef.current = null;
      }
    };

    // Seeking a not-yet-started video reloads the embed with ?startTime,
    // which swaps the iframe's document and orphans the old player handle.
    // Re-attaching on every load keeps the handle pointing at a live player.
    frame?.addEventListener('load', attach);

    let tag = document.querySelector<HTMLScriptElement>(`script[src="${STREAM_SDK}"]`);
    if ((window as any).Stream) {
      attach();
    } else {
      if (!tag) {
        tag = document.createElement('script');
        tag.src = STREAM_SDK;
        tag.async = true;
        document.head.appendChild(tag);
      }
      tag.addEventListener('load', attach);
    }
    return () => {
      cancelled = true;
      frame?.removeEventListener('load', attach);
      tag?.removeEventListener('load', attach);
    };
  }, [iframeRef, enabled]);

  const seek = useCallback(
    (seconds: number) => {
      const player = playerRef.current;
      // A player that has not loaded its metadata yet reports duration 0,
      // and assigning currentTime on it is silently dropped — the chapter
      // click would look dead until the learner pressed play first. Only
      // the reload path can open a cold video at an offset, so require a
      // real duration before trusting the in-place seek.
      const ready =
        player && Number.isFinite(player.duration) && player.duration > 0;
      if (ready) {
        try {
          player.currentTime = seconds;
          player.play?.();
          setCurrent(seconds);
          return;
        } catch {
          /* fall through to the reload path */
        }
      }
      const el = iframeRef.current;
      if (!el) return;
      const base = el.src.split('?')[0];
      playerRef.current = null;
      el.src = `${base}?startTime=${Math.floor(seconds)}s&autoplay=true`;
      setCurrent(seconds);
    },
    [iframeRef]
  );

  return { seek, current };
};

const ChapterList = ({
  chapters,
  current,
  onSeek,
}: {
  chapters: LessonDetail['chapters'];
  current: number;
  onSeek: (s: number) => void;
}) => {
  const activeIndex = chapters.reduce(
    (acc, c, i) => (current >= c.start_s ? i : acc),
    -1
  );
  return (
    <div className="card p-0 mb-6 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold tracking-tight">Chapters</h2>
        <span className="text-[11px] font-mono text-slate-500">
          {chapters.length} sections
        </span>
      </div>
      <ol className="max-h-[22rem] overflow-y-auto divide-y divide-slate-800/70">
        {chapters.map((c, i) => (
          <li key={`${c.start_s}-${c.title}`}>
            <button
              type="button"
              onClick={() => onSeek(c.start_s)}
              aria-current={i === activeIndex ? 'true' : undefined}
              className={`w-full text-left px-4 py-2.5 flex items-baseline gap-3 transition-colors ${
                i === activeIndex
                  ? 'bg-cyan-500/10 text-cyan-200'
                  : 'hover:bg-slate-800/50 text-slate-300'
              }`}
            >
              <span className="font-mono text-xs text-slate-500 tabular-nums shrink-0 w-16">
                {fmt(c.start_s)}
              </span>
              <span className="flex-1 text-sm leading-snug">{c.title}</span>
              <span className="font-mono text-[11px] text-slate-600 shrink-0">
                {fmt(Math.max(0, c.end_s - c.start_s))}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
};

/* In-browser deck viewer. The pixels come from the entitlement-checked,
 * per-learner-watermarked endpoint — there is no file to download, which is
 * the whole protection model for course materials. crossOrigin with
 * credentials is what lets the <img> carry the session cookie to the API.
 *
 * Present mode uses the browser Fullscreen API (button, or the F key);
 * neighbours of the current slide are prefetched so paging feels instant;
 * and every slide change is reported upward so completion can mean
 * "reached the last slide" rather than "opened the page". */
const SlideViewer = ({
  lesson,
  onSlideViewed,
}: {
  lesson: LessonDetail;
  onSlideViewed?: (slideNumber: number, isLast: boolean) => void;
}) => {
  const slides = lesson.slides;
  const moduleId = lesson.module.id as number;
  // Resume where they left off — position_s carries the furthest slide
  // number for deck lessons.
  const [index, setIndex] = useState(() => {
    const saved = lesson.progress.position_s;
    return saved > 0 ? Math.min(saved, slides.length) - 1 : 0;
  });
  const [imgLoaded, setImgLoaded] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  // Theater mode: a CSS full-viewport overlay used when the native
  // Fullscreen API is unavailable or denied (locked-down corporate
  // browsers, embedded contexts). Present must always work.
  const [theater, setTheater] = useState(false);
  // A movie embedded on the current slide is playing (replaces the still).
  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);
  playingRef.current = playing;
  const stripRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const current = slides[index];
  const presenting = isFullscreen || theater;

  const go = useCallback(
    (delta: number) =>
      setIndex((i) => Math.min(slides.length - 1, Math.max(0, i + delta))),
    [slides.length]
  );

  const togglePresent = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      return;
    }
    if (theater) {
      setTheater(false);
      return;
    }
    const el = shellRef.current;
    if (el?.requestFullscreen) {
      el.requestFullscreen().catch(() => setTheater(true));
    } else {
      setTheater(true);
    }
  }, [theater]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(input|textarea|select)$/i.test(target.tagName)) return;
      // While a slide movie is playing, space belongs to the player.
      if (
        (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') &&
        !(e.key === ' ' && playingRef.current)
      ) {
        e.preventDefault();
        go(1);
      }
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault();
        go(-1);
      }
      if (e.key === 'f' || e.key === 'F') togglePresent();
      if (e.key === 'Escape') setTheater(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, togglePresent]);

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  // Theater mode owns the viewport — stop the page behind it from scrolling.
  useEffect(() => {
    if (!theater) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [theater]);

  // Show the spinner until THIS slide's pixels arrive; leaving a slide
  // always stops its movie.
  useEffect(() => {
    setImgLoaded(false);
    setPlaying(false);
  }, [index]);

  // Report progress upward (furthest slide, and whether it's the last one).
  useEffect(() => {
    if (current) onSlideViewed?.(current.number, index === slides.length - 1);
  }, [index, current, slides.length, onSlideViewed]);

  // Prefetch the neighbours so Next/Prev render from the browser's private
  // cache instead of waiting a full round-trip per keypress.
  useEffect(() => {
    [index + 1, index + 2, index - 1].forEach((i) => {
      const s = slides[i];
      if (!s) return;
      const img = new Image();
      img.crossOrigin = 'use-credentials';
      img.src = slideImageUrl(moduleId, s.number, 'lg');
    });
  }, [index, slides, moduleId]);

  useEffect(() => {
    // Keep the active thumbnail in view as the learner pages through.
    const strip = stripRef.current;
    const active = strip?.querySelector<HTMLElement>(`[data-slide="${index}"]`);
    active?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  }, [index]);

  if (!slides.length || moduleId == null) return null;

  return (
    <div
      ref={shellRef}
      className={`select-none ${
        presenting
          ? `bg-black flex flex-col items-center justify-center px-6 py-4 ${
              theater ? 'fixed inset-0 z-[100]' : 'h-screen w-screen'
            }`
          : 'mb-6'
      }`}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div
        className={`relative overflow-hidden bg-black ${
          presenting
            ? 'flex-1 min-h-0 w-full flex items-center justify-center'
            : 'rounded-xl border border-slate-800'
        }`}
      >
        {playing && current.has_video ? (
          <video
            key={`v-${current.number}`}
            src={slideVideoUrl(moduleId, current.number)}
            controls
            autoPlay
            crossOrigin="use-credentials"
            controlsList="nodownload noremoteplayback"
            disablePictureInPicture
            onContextMenu={(e) => e.preventDefault()}
            className={
              presenting
                ? 'max-h-full max-w-full w-auto h-auto object-contain'
                : 'w-full h-auto block max-h-[80vh] bg-black'
            }
          />
        ) : (
          <img
            key={current.number}
            src={slideImageUrl(moduleId, current.number, 'lg')}
            crossOrigin="use-credentials"
            draggable={false}
            onLoad={() => setImgLoaded(true)}
            alt={current.title || `Slide ${current.number}`}
            className={
              presenting
                ? 'max-h-full max-w-full w-auto h-auto object-contain'
                : 'w-full h-auto block'
            }
          />
        )}
        {!imgLoaded && !playing && (
          <div className="absolute inset-0 grid place-items-center bg-slate-950/70 z-20">
            <span className="inline-flex items-center gap-2 text-sm font-mono uppercase tracking-widest text-cyan-400">
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
              Loading slide {current.number}…
            </span>
          </div>
        )}
        <Watermark text={lesson.watermark} />
        {/* Click zones: left third back, rest forward. Hidden while a movie
            plays so they never sit over the player's controls. */}
        {!playing && (
          <>
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
          </>
        )}
        {/* This slide carries a movie — offer Play over the still. */}
        {current.has_video && !playing && (
          <button
            type="button"
            aria-label="Play the video on this slide"
            onClick={() => setPlaying(true)}
            className="absolute inset-0 z-30 grid place-items-center group"
          >
            <span className="grid place-items-center w-20 h-20 rounded-full bg-slate-950/70 border border-cyan-400/60 shadow-lg backdrop-blur-sm transition-transform group-hover:scale-110">
              <Play className="w-9 h-9 text-cyan-300 translate-x-0.5" aria-hidden="true" />
            </span>
            <span className="absolute bottom-4 px-3 py-1 rounded-full bg-slate-950/80 border border-slate-700 text-xs font-mono uppercase tracking-widest text-cyan-300">
              This slide has a video. Click to play
            </span>
          </button>
        )}
        {playing && (
          <>
            <button
              type="button"
              aria-label="Close the video and return to the slide"
              onClick={() => setPlaying(false)}
              className="absolute top-3 right-3 z-30 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-950/80 border border-slate-600 text-xs text-slate-200 hover:border-cyan-400"
            >
              <X className="w-3.5 h-3.5" aria-hidden="true" /> Back to slide
            </button>
            {/* Escape hatch for browsers that throttle embedded media
                (corporate policies, battery savers): a top-level open of the
                same gated URL — the session cookie rides along. */}
            <a
              href={slideVideoUrl(moduleId, current.number)}
              target="_blank"
              rel="noopener noreferrer"
              className="absolute bottom-3 right-3 z-30 px-2.5 py-1 rounded-full bg-slate-950/80 border border-slate-700 text-[11px] text-slate-400 hover:text-cyan-300 hover:border-cyan-500/50"
            >
              Trouble playing? Open in a new tab
            </a>
          </>
        )}
      </div>

      <div
        className={`flex items-center justify-between gap-3 mt-3 ${
          presenting ? 'w-full max-w-3xl shrink-0' : ''
        }`}
      >
        <button type="button" onClick={() => go(-1)} disabled={index === 0}
          className="btn-secondary disabled:opacity-40">
          <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Prev
        </button>
        <div className="text-sm text-slate-400 font-mono flex items-center gap-4">
          <span>
            {index + 1} / {slides.length}
          </span>
          {current.section && !presenting ? (
            <span className="text-slate-500 hidden sm:inline">{current.section}</span>
          ) : null}
          <button
            type="button"
            onClick={togglePresent}
            className="btn-secondary !py-1.5 !px-3 text-xs"
            title={presenting ? 'Exit presentation (F or Esc)' : 'Present fullscreen (F)'}
          >
            {presenting ? (
              <>
                <Minimize2 className="w-3.5 h-3.5" aria-hidden="true" /> Exit
              </>
            ) : (
              <>
                <Maximize2 className="w-3.5 h-3.5" aria-hidden="true" /> Present
              </>
            )}
          </button>
        </div>
        <button type="button" onClick={() => go(1)} disabled={index === slides.length - 1}
          className="btn-secondary disabled:opacity-40">
          Next <ArrowRight className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      {!presenting && (
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
      )}
    </div>
  );
};

const Lesson: React.FC = () => {
  const { lessonId } = useParams();
  const navigate = useNavigate();
  const id = Number(lessonId);

  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [error, setError] = useState('');
  // Structured gate refusal — lets us link to the blocking evaluation.
  const [gate, setGate] = useState<GateBlock | null>(null);
  const [loading, setLoading] = useState(true);
  const [completed, setCompleted] = useState(false);

  const lastBeat = useRef<number>(Date.now());
  // For deck lessons: the furthest slide number reached this session.
  // Reported as position_s so the server can mark the deck complete only
  // when the LAST slide has actually been reached.
  const maxSlideRef = useRef<number>(0);

  // Chapter navigation drives the Stream iframe in place; the hook only
  // attaches once a video lesson is actually on screen.
  const videoFrame = useRef<HTMLIFrameElement>(null);
  const { seek, current: playhead } = useStreamPlayer(
    videoFrame,
    lesson?.kind === 'video' && !!lesson.playback
  );

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
        maxSlideRef.current =
          data.kind === 'slides' ? data.progress.position_s || 0 : 0;
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          navigate('/learn/signin', { replace: true });
          return;
        }
        if (err instanceof ApiError && err.info?.code === 'gate_locked') {
          setGate(err.info);
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
    // Decks report the furthest slide as position; a zero-delta beat is
    // still worth sending there (it can carry the finish). Everything else
    // keeps the original time-based behavior.
    if (delta <= 0 && lesson.kind !== 'slides') return;
    const position =
      lesson.kind === 'slides'
        ? maxSlideRef.current
        : lesson.progress.position_s + delta;
    try {
      const res = await academy.heartbeat(lesson.id, position, Math.max(delta, 0));
      if (res.completed) setCompleted(true);
    } catch {
      /* a dropped beat is not worth interrupting the lesson for */
    }
  }, [lesson]);

  const onSlideViewed = useCallback(
    (slideNumber: number, isLast: boolean) => {
      if (slideNumber > maxSlideRef.current) {
        maxSlideRef.current = slideNumber;
        // Reaching the end shouldn't wait for the next 15s heartbeat.
        if (isLast) void beat();
      }
    },
    [beat]
  );

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
          <h1 className="text-xl font-bold mb-3">
            {gate ? 'Finish the previous section first' : "This lesson isn't available"}
          </h1>
          <p className="text-slate-300 mb-6">{error}</p>
          {gate?.needs === 'quiz' ? (
            <div className="flex flex-wrap gap-3 justify-center">
              <Link
                to={`/learn/quiz/${gate.blocking_module_id}/formative`}
                className="btn-primary"
              >
                Take the {gate.blocking_module_code} evaluation
              </Link>
              <Link to="/learn" className="btn-secondary">
                Back to your course
              </Link>
            </div>
          ) : (
            <Link to="/learn" className="btn-secondary">
              Back to your course
            </Link>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="relative pt-28 pb-20">
      <div className="absolute inset-0 -z-10 bg-hero-radial" />
      {/* Decks get more room — the slide is the content. */}
      <div
        className={`container-site ${
          lesson.kind === 'slides' && lesson.slides.length > 0
            ? 'max-w-6xl'
            : 'max-w-4xl'
        }`}
      >
        <Link
          to={lesson.module.product_code ? `/learn/${lesson.module.product_code}` : '/learn'}
          className="btn-ghost mb-6"
        >
          <ArrowLeft className="w-4 h-4" aria-hidden="true" />
          {lesson.module.code}: {lesson.module.title}
        </Link>

        <h1 className="text-2xl md:text-3xl font-bold tracking-tight mb-6">{lesson.title}</h1>

        {lesson.kind === 'video' && (
          <div className="relative rounded-xl overflow-hidden border border-slate-800 bg-black aspect-video mb-6">
            {lesson.playback ? (
              <>
                <iframe
                  ref={videoFrame}
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

        {lesson.kind === 'video' && lesson.playback && lesson.chapters.length > 0 && (
          <ChapterList
            chapters={lesson.chapters}
            current={playhead}
            onSeek={seek}
          />
        )}

        {lesson.kind === 'slides' &&
          (lesson.slides.length > 0 ? (
            <SlideViewer lesson={lesson} onSlideViewed={onSlideViewed} />
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
              Training simulation only: generic behavior, not any specific
              engine. Never apply values from it to real equipment. Your access
              is personal and watermarked with your account email. The tool runs
              only from this site while you are signed in; a saved copy will not
              start, and each launch stays valid for 24 hours, so simply launch
              it again when you come back.
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
              account carries across, with no separate sign-in.
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
          registered to {lesson.watermark || 'your account'} for training use
          only, never for operation of real equipment.
        </p>
      </div>
    </div>
  );
};

export default Lesson;
