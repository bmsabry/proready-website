import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  Menu,
  X,
  ArrowRight,
  GraduationCap,
  ChevronDown,
  BookOpen,
  LogOut,
  CalendarClock,
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { academy, Me } from '../lib/academyApi';
import Img from './Img';
import { CONSULT_PUBLIC } from '../lib/features';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/* The learner entry point.
 *
 * Every visitor sees one unmistakable way into their courses, in the same
 * place on every page: a pill next to the main call to action. Signed out it
 * reads "Learner Sign In" and goes to the passwordless sign-in; signed in it
 * becomes "My Learning" with a small menu (courses & certificates, sign out).
 * The session is a cookie on the API origin, so the state is discovered
 * client-side after hydration; the prerendered HTML shows the signed-out
 * pill, which is the right default for a first visit. */

const pillClass =
  'inline-flex items-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2.5 ' +
  'text-sm font-semibold text-cyan-300 transition-colors hover:bg-cyan-500/20 hover:text-white ' +
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60 whitespace-nowrap';

const useLearnerSession = (pathname: string) => {
  const [me, setMe] = useState<Me | null>(null);
  const refresh = useCallback(() => {
    let cancelled = false;
    academy
      .me()
      .then((m) => {
        if (!cancelled) setMe(m);
      })
      .catch(() => {
        if (!cancelled) setMe({ signed_in: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  // Check once on arrival, then again only when the route enters or leaves
  // /learn: that is where signing in and out happen, and the pill must
  // follow without a reload. Browsing the marketing pages costs nothing.
  const prev = useRef<string | null>(null);
  useEffect(() => {
    const was = prev.current;
    prev.current = pathname;
    if (was !== null && !was.startsWith('/learn') && !pathname.startsWith('/learn')) return;
    return refresh();
  }, [refresh, pathname]);
  return { me, setMe };
};

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const { me, setMe } = useLearnerSession(location.pathname);
  const signedIn = Boolean(me?.signed_in);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    setIsOpen(false);
    setMenuOpen(false);
  }, [location.pathname]);

  // Close the account menu on an outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  // Escape closes the mobile navigation too.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen]);

  const signOut = async () => {
    setMenuOpen(false);
    setIsOpen(false);
    try {
      await academy.logout();
    } finally {
      setMe({ signed_in: false });
      if (location.pathname.startsWith('/learn')) navigate('/learn/signin', { replace: true });
    }
  };

  // "New" badge on Products: pulls attention until the date below, then
  // removes itself — no redeploy needed. Rendered client-side only (after
  // hydration) so build-time HTML never disagrees with the visitor's clock.
  const PRODUCTS_NEW_UNTIL = Date.parse('2026-09-15T00:00:00Z');
  const [showNewBadge, setShowNewBadge] = useState(false);
  useEffect(() => { setShowNewBadge(Date.now() < PRODUCTS_NEW_UNTIL); }, [PRODUCTS_NEW_UNTIL]);
  const newBadge = (
    <span
      className="ml-1.5 align-middle text-[10px] font-bold uppercase tracking-wider
        bg-amber-400/15 text-amber-300 border border-amber-400/40 rounded-full px-1.5 py-0.5"
      aria-label="New section"
    >
      New
    </span>
  );

  const navLinks = [
    { name: 'Home', path: '/' },
    { name: 'Services', path: '/services' },
    { name: 'Products', path: '/products', isNew: true },
    { name: 'Training', path: '/training' },
    { name: 'Research Insights', path: '/insights' },
    { name: 'Case Studies', path: '/case-studies' },
    { name: 'Testimonials', path: '/testimonials' },
  ];

  const isActive = (path: string) =>
    path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);
  const learnActive = location.pathname.startsWith('/learn');
  const consultActive = location.pathname.startsWith('/consult');

  const learnerPill = signedIn ? (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-controls="learner-menu"
        className={cn(pillClass, (menuOpen || learnActive) && 'bg-cyan-500/20 text-white')}
      >
        <span className="relative">
          <GraduationCap className="w-4 h-4" aria-hidden="true" />
          <span
            className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-emerald-400 ring-2 ring-slate-950"
            aria-hidden="true"
          />
        </span>
        {/* With the Book button the desktop bar needs the room "My " took at 2xl. */}
        <span>{CONSULT_PUBLIC ? null : <span className="hidden 2xl:inline">My </span>}Learning</span>
        <ChevronDown
          className={cn('w-3.5 h-3.5 transition-transform', menuOpen && 'rotate-180')}
          aria-hidden="true"
        />
      </button>
      {menuOpen && (
        <div
          id="learner-menu"
          role="menu"
          className="absolute right-0 mt-2 w-72 rounded-xl border border-slate-700/80 bg-slate-900/95 backdrop-blur-md shadow-card p-2 z-50"
        >
          <div className="px-3 py-2 text-xs text-slate-400 border-b border-slate-800 mb-1">
            Signed in as{' '}
            <span className="block truncate text-white font-medium" title={me?.email}>
              {me?.full_name || me?.email}
            </span>
          </div>
          <Link
            role="menuitem"
            to="/learn"
            onClick={() => setMenuOpen(false)}
            className="flex items-start gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-200 hover:bg-slate-800/80 hover:text-white"
          >
            <BookOpen className="w-4 h-4 mt-0.5 text-cyan-400 shrink-0" aria-hidden="true" />
            <span>
              <span className="block font-medium">My courses &amp; certificates</span>
              <span className="block text-xs text-slate-400">
                Continue where you left off, download your certificates
              </span>
            </span>
          </Link>
          <button
            role="menuitem"
            type="button"
            onClick={signOut}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-800/80 hover:text-white"
          >
            <LogOut className="w-4 h-4 text-slate-400" aria-hidden="true" /> Sign out
          </button>
        </div>
      )}
    </div>
  ) : (
    <Link
      to="/learn/signin"
      className={cn(pillClass, learnActive && 'bg-cyan-500/20 text-white')}
      title="Sign in to see your courses and certificates"
    >
      <GraduationCap className="w-4 h-4" aria-hidden="true" />
      <span>{CONSULT_PUBLIC ? null : <span className="hidden 2xl:inline">Learner </span>}Sign In</span>
    </Link>
  );

  return (
    <nav className={cn(
      'fixed w-full z-50 transition-all duration-300',
      scrolled || isOpen ? 'glass py-3' : 'bg-transparent py-5'
    )}>
      <div className="container-site">
        <div className="flex justify-between items-center">
          <Link to="/" className="flex items-center space-x-3 shrink-0">
            <Img
              src="/Logo.jpg" sizes="40px" priority
              alt=""
              className="h-10 w-auto rounded-md"
            />
            <span className="font-display text-xl font-bold tracking-tight whitespace-nowrap">
              ProReady<span className="text-cyan-400">Engineer</span>
            </span>
          </Link>

          {/* Desktop Nav */}
          {/* The full bar needs about 1,000 px beside the logo; below xl the
              menu button takes over and the learner pill stays visible. */}
          {/* Hidden release: production's bar, except the 2xl link gap (24 -> 22 px):
              at 24 px it ran 4 px (signed out) / 8 px (signed in) past the container. */}
          <div className={cn('hidden xl:flex items-center ml-6', CONSULT_PUBLIC ? 'gap-3' : 'gap-4 2xl:gap-[22px]')}>
            {navLinks.map((link) => (
              <Link
                key={link.name}
                to={link.path}
                className={cn(
                  'relative text-sm font-medium transition-colors hover:text-cyan-400 py-1 whitespace-nowrap',
                  isActive(link.path) ? 'text-cyan-400' : 'text-slate-300'
                )}
              >
                {link.name}
                {'isNew' in link && link.isNew && showNewBadge && newBadge}
                {isActive(link.path) && (
                  <span className="absolute -bottom-0.5 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-400 to-transparent" aria-hidden="true" />
                )}
              </Link>
            ))}
            <div className={cn('flex items-center ml-1', CONSULT_PUBLIC ? 'gap-2' : 'gap-2.5')}>
              {learnerPill}
              {CONSULT_PUBLIC && (
              <Link
                to="/consult"
                className={cn(
                  'btn-secondary py-2.5 px-3 text-sm whitespace-nowrap',
                  consultActive && 'border-cyan-500/60 text-cyan-300'
                )}
                aria-current={consultActive ? 'page' : undefined}
                aria-label="Book a call with an expert"
                title="Book a call with an expert"
              >
                <CalendarClock className="w-4 h-4" aria-hidden="true" />
                {/* The desktop bar is always 1,216 px wide (the container stops
                    growing at 1,280). "Book a Call" fits beside "Sign In"; beside
                    the wider signed-in "Learning" menu only "Book" does
                    (measured: tools/consult/header.mjs). */}
                <span>{signedIn ? 'Book' : 'Book a Call'}</span>
              </Link>
              )}
              <Link to="/contact" className={cn('btn-primary py-2.5 text-sm whitespace-nowrap', CONSULT_PUBLIC ? 'px-3' : 'px-3.5')}>
                Get in Touch <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </Link>
            </div>
          </div>

          {/* Mobile and tablet: the learner pill stays visible next to the menu button */}
          <div className={cn('xl:hidden flex items-center', CONSULT_PUBLIC ? 'gap-1.5 sm:gap-2' : 'gap-2')}>
            {CONSULT_PUBLIC && (
            <Link
              to="/consult"
              className={cn(
                'btn-secondary px-2.5 sm:px-3 py-2 text-sm whitespace-nowrap',
                consultActive && 'border-cyan-500/60 text-cyan-300'
              )}
              aria-label="Book a call with an expert"
            >
              <CalendarClock className="w-4 h-4" aria-hidden="true" />
              <span className="hidden sm:inline">Book a Call</span>
            </Link>
            )}
            <Link
              to={signedIn ? '/learn' : '/learn/signin'}
              className={cn(pillClass, 'px-3 py-2', learnActive && 'bg-cyan-500/20 text-white')}
              aria-label={signedIn ? 'My Learning: your courses and certificates' : 'Learner sign in'}
            >
              <GraduationCap className="w-4 h-4" aria-hidden="true" />
              <span className="hidden sm:inline">{signedIn ? 'My Learning' : 'Sign In'}</span>
            </Link>
            <button
              onClick={() => setIsOpen(!isOpen)}
              className="p-2 text-slate-300 hover:text-white transition-colors"
              aria-label={isOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={isOpen}
              aria-controls="mobile-menu"
            >
              {isOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Nav */}
      {isOpen && (
        <div id="mobile-menu" className="xl:hidden glass absolute top-full left-0 w-full py-4 px-4 space-y-1 border-t border-slate-800">
          {navLinks.map((link) => (
            <Link
              key={link.name}
              to={link.path}
              onClick={() => setIsOpen(false)}
              className={cn(
                'block rounded-lg px-3 py-2.5 text-base font-medium transition-colors',
                isActive(link.path) ? 'text-cyan-400 bg-cyan-500/5' : 'text-slate-300 hover:text-cyan-400 hover:bg-slate-800/50'
              )}
            >
              {link.name}
              {'isNew' in link && link.isNew && showNewBadge && newBadge}
            </Link>
          ))}
          <div className="pt-3 mt-2 border-t border-slate-800 space-y-2">
            {signedIn ? (
              <>
                <p className="px-3 text-xs text-slate-400 truncate">
                  Signed in as <span className="text-white">{me?.full_name || me?.email}</span>
                </p>
                <Link
                  to="/learn"
                  onClick={() => setIsOpen(false)}
                  className={cn(pillClass, 'w-full justify-center py-3')}
                >
                  <GraduationCap className="w-4 h-4" aria-hidden="true" /> My courses &amp; certificates
                </Link>
                <button
                  type="button"
                  onClick={signOut}
                  className="btn-ghost w-full justify-center py-2 text-slate-300"
                >
                  <LogOut className="w-4 h-4" aria-hidden="true" /> Sign out
                </button>
              </>
            ) : (
              <Link
                to="/learn/signin"
                onClick={() => setIsOpen(false)}
                className={cn(pillClass, 'w-full justify-center py-3')}
              >
                <GraduationCap className="w-4 h-4" aria-hidden="true" /> Learner Sign In
              </Link>
            )}
            {CONSULT_PUBLIC && (
              <Link
                to="/consult"
                onClick={() => setIsOpen(false)}
                className="btn-secondary w-full text-center"
              >
                <CalendarClock className="w-4 h-4" aria-hidden="true" /> Book a Call with an Expert
              </Link>
            )}
            <Link
              to="/contact"
              onClick={() => setIsOpen(false)}
              className="btn-primary w-full text-center"
            >
              Get in Touch
            </Link>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
