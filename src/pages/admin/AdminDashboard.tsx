/**
 * Admin dashboard shell — persistent left sidebar + view router.
 *
 * The heavy lifting lives in the page modules (OverviewPage, CoursesPage,
 * CourseWorkspace, AcademyPage, SoftwarePage, CommsPage, AiPage); this file
 * only handles session, navigation, and the URL-hash sync that makes a
 * refresh land back on the same view (#courses/<code>/<tab>, #software/<slug>).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BookOpen,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Mail,
  MonitorDown,
  Sparkles,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { API_BASE, AuthError, api, hashFor, parseHash, type ViewState } from './lib';
import { Notice } from './ui';
import OverviewPage from './OverviewPage';
import CoursesPage from './CoursesPage';
import CourseWorkspace from './CourseWorkspace';
import AcademyPage from './AcademyPage';
import SoftwarePage from './SoftwarePage';
import CommsPage from './CommsPage';
import AiPage from './AiPage';
import ChatWidget from './ChatWidget';
import ViewErrorBoundary from './ViewErrorBoundary';

const NAV: { page: ViewState['page']; label: string; icon: LucideIcon }[] = [
  { page: 'overview', label: 'Overview', icon: LayoutDashboard },
  { page: 'courses', label: 'Courses', icon: BookOpen },
  { page: 'academy', label: 'Academy', icon: GraduationCap },
  { page: 'software', label: 'Software', icon: MonitorDown },
  { page: 'comms', label: 'Comms', icon: Mail },
  { page: 'ai', label: 'AI Assistant', icon: Sparkles },
];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [view, setView] = useState<ViewState>(() =>
    typeof window === 'undefined' ? { page: 'overview' } : parseHash(window.location.hash),
  );
  const [adminEmail, setAdminEmail] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

  const onAuthError = useCallback(() => {
    navigate('/admin/login', { replace: true });
  }, [navigate]);

  // Hash is the single source of truth for navigation — back/forward works,
  // refresh restores the exact view.
  useEffect(() => {
    const onHash = () => setView(parseHash(window.location.hash));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  /**
   * Navigate. `replace` swaps the current history entry instead of adding one —
   * used for switching tabs inside a course, so that Back leaves the course in
   * a single press rather than walking back through every tab that was opened.
   */
  const go = useCallback((v: ViewState, opts?: { replace?: boolean }) => {
    const h = hashFor(v);
    if (window.location.hash === h) {
      setView(v);
    } else if (opts?.replace) {
      window.history.replaceState(null, '', h);
      setView(v); // replaceState fires no hashchange, so sync state here
    } else {
      window.location.hash = h; // pushes; the hashchange listener syncs state
    }
  }, []);

  // Session check — same behaviour as before: 401 bounces to /admin/login.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!API_BASE) {
        setFatal('VITE_API_BASE is not configured.');
        return;
      }
      try {
        const me = await api<{ email: string }>('/api/admin/me');
        if (!cancelled) setAdminEmail(me.email);
      } catch (e) {
        if (cancelled) return;
        if (e instanceof AuthError) onAuthError();
        else setFatal(e instanceof Error ? e.message : 'Session check failed.');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onAuthError]);

  async function handleLogout() {
    if (API_BASE) {
      try {
        await fetch(`${API_BASE}/api/admin/logout`, { method: 'POST', credentials: 'include' });
      } catch {
        /* ignore */
      }
    }
    navigate('/admin/login', { replace: true });
  }

  let content: React.ReactNode;
  switch (view.page) {
    case 'courses': {
      const code = view.course;
      content = code ? (
        <CourseWorkspace
          key={code}
          code={code}
          tab={view.tab ?? 'registrations'}
          onTab={(t) => go({ page: 'courses', course: code, tab: t }, { replace: true })}
          onBack={() => go({ page: 'courses' })}
          onAuthError={onAuthError}
        />
      ) : (
        <CoursesPage
          onAuthError={onAuthError}
          openCourse={(c) => go({ page: 'courses', course: c, tab: 'registrations' })}
        />
      );
      break;
    }
    case 'academy':
      content = <AcademyPage onAuthError={onAuthError} />;
      break;
    case 'software':
      content = (
        <SoftwarePage
          slug={view.slug ?? null}
          openSlug={(s) => go(s ? { page: 'software', slug: s } : { page: 'software' })}
          onAuthError={onAuthError}
        />
      );
      break;
    case 'comms':
      content = <CommsPage onAuthError={onAuthError} />;
      break;
    case 'ai':
      content = <AiPage onAuthError={onAuthError} />;
      break;
    default:
      content = <OverviewPage onAuthError={onAuthError} go={go} />;
  }

  return (
    <section className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 pt-24 pb-10 px-3 sm:px-4 lg:px-6">
      <div className="max-w-[1440px] mx-auto flex items-start gap-3 lg:gap-6">
        {/* Sidebar — collapses to icons below lg */}
        <aside className="sticky top-24 shrink-0 w-14 lg:w-56 bg-slate-900/70 border border-slate-800 rounded-2xl p-2 lg:p-3 flex flex-col gap-1 min-h-[calc(100vh-9rem)]">
          <div className="hidden lg:block px-2.5 pb-2 pt-1">
            <span className="eyebrow">Admin</span>
          </div>
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = view.page === item.page;
            return (
              <button
                key={item.page}
                onClick={() => go({ page: item.page } as ViewState)}
                title={item.label}
                className={`w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors border ${
                  active
                    ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'
                    : 'text-slate-300 hover:text-white hover:bg-slate-800/60 border-transparent'
                }`}
                aria-current={active ? 'page' : undefined}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className="hidden lg:inline truncate">{item.label}</span>
              </button>
            );
          })}

          <div className="mt-auto pt-2 border-t border-slate-800">
            {adminEmail && (
              <div
                className="hidden lg:block text-[11px] text-slate-400 truncate px-2.5 pb-1.5"
                title={`Signed in as ${adminEmail}`}
              >
                {adminEmail}
              </div>
            )}
            <button
              onClick={() => void handleLogout()}
              title="Sign out"
              className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors"
            >
              <LogOut className="w-4 h-4 shrink-0" />
              <span className="hidden lg:inline">Sign out</span>
            </button>
          </div>
        </aside>

        {/* Active view */}
        <main className="flex-1 min-w-0">
          {fatal && <Notice kind="error">{fatal}</Notice>}
          {/* A crash in one view must not take down the shell: the hash router
              never reloads the document, so a dead tree means the sidebar and
              the back button stop working too. */}
          <ViewErrorBoundary resetKey={hashFor(view)}>{content}</ViewErrorBoundary>
        </main>
      </div>

      {/* Floating AI chat — available on every admin page */}
      <ChatWidget onAuthError={onAuthError} />
    </section>
  );
}
