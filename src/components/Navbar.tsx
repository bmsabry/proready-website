import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, X, ArrowRight } from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => { setIsOpen(false); }, [location.pathname]);

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

  return (
    <nav className={cn(
      'fixed w-full z-50 transition-all duration-300',
      scrolled || isOpen ? 'glass py-3' : 'bg-transparent py-5'
    )}>
      <div className="container-site">
        <div className="flex justify-between items-center">
          <Link to="/" className="flex items-center space-x-3">
            <img
              src="/Logo.jpg"
              alt=""
              width="40"
              height="40"
              className="h-10 w-auto rounded-md"
            />
            <span className="font-display text-xl font-bold tracking-tight">
              ProReady<span className="text-cyan-400">Engineer</span>
            </span>
          </Link>

          {/* Desktop Nav */}
          <div className="hidden lg:flex items-center gap-7">
            {navLinks.map((link) => (
              <Link
                key={link.name}
                to={link.path}
                className={cn(
                  'relative text-sm font-medium transition-colors hover:text-cyan-400 py-1',
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
            <Link to="/contact" className="btn-primary py-2.5 px-5 text-sm">
              Get in Touch <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </Link>
          </div>

          {/* Mobile Menu Button */}
          <div className="lg:hidden">
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
        <div id="mobile-menu" className="lg:hidden glass absolute top-full left-0 w-full py-4 px-4 space-y-1 border-t border-slate-800">
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
          <Link
            to="/contact"
            onClick={() => setIsOpen(false)}
            className="btn-primary w-full text-center mt-3"
          >
            Get in Touch
          </Link>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
