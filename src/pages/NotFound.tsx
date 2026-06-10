import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { usePageMeta } from '../lib/meta';

const NotFound = () => {
  usePageMeta('Page Not Found', 'The page you were looking for does not exist.', { noindex: true });

  return (
    <div className="min-h-[70vh] flex items-center justify-center pt-32 pb-20">
      <div className="container-site text-center">
        <p className="font-mono text-sm text-cyan-500 mb-4">404</p>
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-4">Page not found</h1>
        <p className="text-slate-400 max-w-md mx-auto mb-8">
          That address doesn't match anything on our site. It may have moved, or the link may be out of date.
        </p>
        <div className="flex flex-col sm:flex-row justify-center gap-4">
          <Link to="/" className="btn-primary">
            Back to home <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </Link>
          <Link to="/case-studies" className="btn-secondary">Browse case studies</Link>
        </div>
      </div>
    </div>
  );
};

export default NotFound;
