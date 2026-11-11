import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { MessageCircle } from 'lucide-react';
import { chatApi, type ChatStatusOut } from '../../lib/chatApi';

/* The floating "Ask the AI assistant" button.
 *
 * Fetched after the page has settled (see ChatMount). It asks the API once
 * per browser session whether the assistant is switched on; that request
 * sets no cookie. Switched off, or unreachable: no button at all, rather
 * than a button that opens onto an apology.
 *
 * The conversation panel is a separate file, fetched on the first open. */

const ChatPanel = lazy(() => import('./ChatPanel'));

const CACHE_KEY = 'pre:chat-enabled';
const CACHE_MS = 10 * 60 * 1000;

type Cached = { at: number; enabled: boolean; disclosure?: string };

const readCache = (): Cached | null => {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as Cached;
    return Date.now() - c.at < CACHE_MS ? c : null;
  } catch {
    return null;
  }
};

const cachedEnabled = (): boolean | null => {
  const c = readCache();
  return c ? Boolean(c.enabled) : null;
};

const rememberEnabled = (enabled: boolean, disclosure?: string) => {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), enabled, disclosure }));
  } catch {
    /* private mode: ask again next page */
  }
};

/* One status request per page load, however often the effect below runs
   (React's development mode runs every effect twice). */
let statusOnce: Promise<ChatStatusOut> | null = null;
const fetchStatusOnce = (): Promise<ChatStatusOut> => {
  if (!statusOnce) {
    statusOnce = chatApi.status();
    statusOnce.catch(() => {
      statusOnce = null; // a failed check may be tried again on the next page
    });
  }
  return statusOnce;
};

export default function ChatLauncher() {
  const [enabled, setEnabled] = useState<boolean | null>(() => cachedEnabled());
  const [status, setStatus] = useState<ChatStatusOut | null>(null);
  const [open, setOpen] = useState(false);
  // Once opened, the panel stays mounted (hidden) so a conversation survives
  // closing and reopening it.
  const [everOpened, setEverOpened] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (enabled !== null) return;
    let cancelled = false;
    fetchStatusOnce()
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        setEnabled(s.enabled);
        rememberEnabled(s.enabled, s.disclosure);
      })
      .catch(() => {
        if (!cancelled) setEnabled(false); // unreachable: no button this page
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const close = useCallback(() => setOpen(false), []);

  // Closing hands the keyboard back to the button that opened the panel.
  // Done after the button is back on the page, not on a timer.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
    } else if (wasOpen.current) {
      wasOpen.current = false;
      buttonRef.current?.focus();
    }
  }, [open]);

  const onDisabled = useCallback(() => {
    rememberEnabled(false);
  }, []);

  if (!enabled) return null;

  return (
    <>
      {!open && (
        <button
          ref={buttonRef}
          type="button"
          onClick={() => {
            setEverOpened(true);
            setOpen(true);
          }}
          aria-haspopup="dialog"
          aria-expanded={false}
          aria-controls="site-chat-panel"
          aria-label="Ask our AI assistant"
          data-testid="chat-launcher"
          className="btn-primary anim-enter fixed bottom-4 right-4 z-40 rounded-full px-4 py-3 text-sm"
        >
          <MessageCircle className="w-5 h-5" aria-hidden="true" />
          <span className="hidden sm:inline">Ask our AI assistant</span>
        </button>
      )}
      {everOpened && (
        <Suspense fallback={null}>
          <ChatPanel
            open={open}
            onClose={close}
            initialStatus={status}
            initialDisclosure={status?.disclosure ?? readCache()?.disclosure ?? ''}
            onDisabled={onDisabled}
          />
        </Suspense>
      )}
    </>
  );
}
