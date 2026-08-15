/**
 * Error boundary around the admin dashboard's active view.
 *
 * Why this exists: the dashboard navigates by URL hash, and a hash change does
 * not reload the document. So when a render threw, React tore the whole tree
 * down and the app was *dead* — the sidebar vanished, the back button changed
 * the hash but nothing re-rendered, and the only escape was pressing back
 * enough times to leave /admin entirely and force a real page load. One bad
 * tab took out the entire admin panel and its navigation with it.
 *
 * With this in place a crash is contained to the one view: the shell, the
 * sidebar and the hash router keep working, the error is shown instead of a
 * blank screen, and `resetKey` clears it automatically the moment you navigate
 * somewhere else.
 */
import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

type Props = {
  /** Change this (e.g. the current hash) to clear the error on navigation. */
  resetKey: string;
  children: React.ReactNode;
};

type State = { error: Error | null };

export default class ViewErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props) {
    // Navigating away from a broken view clears it — no reload needed.
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Admin view crashed:', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-400" />
          <div className="min-w-0">
            <h2 className="font-semibold text-white">This section failed to load</h2>
            <p className="mt-1 text-sm text-rose-200">
              Something in this view threw an error. The rest of the dashboard is
              fine — pick another section in the sidebar, or use the browser back
              button; both still work.
            </p>
            <p className="mt-3 break-words font-mono text-xs text-rose-300/90">
              {error.message || String(error)}
            </p>
            <div className="mt-4 flex gap-2">
              <button
                onClick={() => this.setState({ error: null })}
                className="flex items-center gap-1.5 rounded-lg border border-rose-400/40 px-3 py-1.5 text-xs text-rose-100 hover:bg-rose-500/20"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Try again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-400"
              >
                Reload the page
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
