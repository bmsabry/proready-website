/**
 * Error boundary around every page (public site and learner portal).
 *
 * Without one, any error while drawing a page unmounts the whole app and the
 * visitor is left looking at a blank navy screen with no way forward. Two
 * things it does:
 *
 * 1. After a new version of the site is published, a tab that was already open
 *    still holds the old page list. Its next click asks for a file that no
 *    longer exists, and loading that page fails. This is the one error with a
 *    known cure, so it is applied automatically: reload once and the visitor
 *    lands on the page they asked for, on the new version. A learner in the
 *    middle of a course never notices a release.
 *
 * 2. For anything else, the header and footer stay up and the page area says
 *    what happened, with a way to reload or leave. Moving to another page
 *    clears it.
 */
import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

type Props = {
  /** The current path: changing it clears a shown error. */
  resetKey: string;
  children: React.ReactNode;
};
type State = { error: Error | null };

const RELOAD_MARK = 'pre:page-reloaded-at';
const RELOAD_GUARD_MS = 30_000;

/** A page's code file could not be fetched (it was replaced by a newer release). */
export const isStaleBuildError = (error: unknown): boolean =>
  /dynamically imported module|importing a module script failed|chunkloaderror|is not a valid javascript mime type/i.test(
    String((error as Error | undefined)?.message ?? error ?? ''),
  );

const reloadedRecently = (): boolean => {
  try {
    const at = Number(sessionStorage.getItem(RELOAD_MARK) ?? 0);
    return Date.now() - at < RELOAD_GUARD_MS;
  } catch {
    return true; // storage unavailable: never risk a reload loop
  }
};

export default class PageErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    if (isStaleBuildError(error) && !reloadedRecently()) {
      try {
        sessionStorage.setItem(RELOAD_MARK, String(Date.now()));
      } catch {
        return; // cannot record the reload, so do not attempt it
      }
      window.location.reload();
      return;
    }
    console.error('Page failed to render:', error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const stale = isStaleBuildError(error);
    return (
      <div className="min-h-[70vh] flex items-center justify-center pt-32 pb-20">
        <div className="container-site">
          <div role="alert" className="card max-w-xl mx-auto p-8 text-center">
            <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto mb-4" aria-hidden="true" />
            <h1 className="text-2xl font-bold tracking-tight mb-3">
              {stale ? 'This page needs a refresh' : 'This page could not be shown'}
            </h1>
            <p className="text-slate-300 text-sm leading-relaxed mb-6">
              {stale
                ? 'The site was updated while this tab was open. Reload to continue where you were.'
                : 'Something went wrong while loading this page. Reloading usually fixes it.'}
            </p>
            <div className="flex flex-col sm:flex-row justify-center gap-3">
              <button type="button" onClick={() => window.location.reload()} className="btn-primary">
                <RefreshCw className="w-4 h-4" aria-hidden="true" /> Reload the page
              </button>
              <a href="/" className="btn-secondary">Back to home</a>
            </div>
            <p className="text-xs text-slate-400 mt-6">
              Still stuck? Email{' '}
              <a className="text-cyan-400 hover:text-cyan-300" href="mailto:info@proreadyengineer.com">
                info@proreadyengineer.com
              </a>
              .
            </p>
          </div>
        </div>
      </div>
    );
  }
}
