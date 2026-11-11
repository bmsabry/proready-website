import React, { Suspense, lazy, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { API_BASE, chatAllowedOn } from '../../lib/chatApi';

/* Where the public AI assistant attaches to the site.
 *
 * This is the only part of it in the main bundle, and it draws nothing: not
 * in the prerendered HTML, and not on first paint. Once the page has settled
 * it fetches the launcher's own small file; the conversation panel is fetched
 * only when a visitor opens it.
 *
 * Public pages only: never under /learn, /admin, /verify or /consult/booking.
 */

const ChatLauncher = lazy(() => import('./ChatLauncher'));

const whenIdle = (run: () => void): (() => void) => {
  const w = window as Window & {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    cancelIdleCallback?: (id: number) => void;
  };
  if (w.requestIdleCallback) {
    const id = w.requestIdleCallback(run, { timeout: 4000 });
    return () => w.cancelIdleCallback?.(id);
  }
  const id = window.setTimeout(run, 1500);
  return () => window.clearTimeout(id);
};

export default function ChatMount() {
  const { pathname } = useLocation();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!API_BASE) return; // no backend on this build: no assistant
    return whenIdle(() => setReady(true));
  }, []);

  if (!ready || !chatAllowedOn(pathname)) return null;
  return (
    <Suspense fallback={null}>
      <ChatLauncher />
    </Suspense>
  );
}
