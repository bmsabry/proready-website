import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export default function ScrollToTop() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (!hash) {
      window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
      return;
    }

    let targetId = hash.slice(1);
    try {
      targetId = decodeURIComponent(targetId);
    } catch {
      // Keep raw fragment if percent-decoding fails.
    }
    if (!targetId) return;

    let disposed = false;
    let rafId: number | null = null;
    let observer: MutationObserver | null = null;
    let timeoutId: number | null = null;

    const cleanup = () => {
      disposed = true;
      if (rafId !== null) {
        window.cancelAnimationFrame(rafId);
        rafId = null;
      }
      if (observer !== null) {
        observer.disconnect();
        observer = null;
      }
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
        timeoutId = null;
      }
    };

    const tryScroll = (): boolean => {
      if (disposed) return true;
      const el = document.getElementById(targetId);
      if (!el) return false;
      el.scrollIntoView();
      cleanup();
      return true;
    };

    if (tryScroll()) return cleanup;

    if (typeof MutationObserver !== 'undefined' && document.body) {
      observer = new MutationObserver(() => {
        void tryScroll();
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }

    let frames = 0;
    const retryRaf = () => {
      if (disposed) return;
      if (tryScroll()) return;
      frames += 1;
      if (frames < 30) {
        rafId = window.requestAnimationFrame(retryRaf);
      }
    };
    rafId = window.requestAnimationFrame(retryRaf);

    timeoutId = window.setTimeout(cleanup, 3000);

    return cleanup;
  }, [pathname, hash]);

  return null;
}
