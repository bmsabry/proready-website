import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Mail } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import { academy, ApiError } from '../../lib/academyApi';

/* Passwordless sign-in.
 *
 * Two jobs in one page. With `?token=...` it exchanges a magic link for a
 * session and redirects. Without one it collects an email and asks the API
 * to send a link — and always reports success, because the API deliberately
 * cannot tell us whether the address exists and we must not leak it either. */

const SignIn: React.FC = () => {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token');

  const [email, setEmail] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [error, setError] = useState('');
  const [verifying, setVerifying] = useState(!!token);

  usePageMeta('Sign in', 'Sign in to your ProReadyEngineer courses.', {
    noindex: true,
  });

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await academy.verify(token);
        if (cancelled) return;
        navigate(res.next_path || '/learn', { replace: true });
      } catch (err) {
        if (cancelled) return;
        setVerifying(false);
        setError(
          err instanceof ApiError
            ? err.message
            : 'That sign-in link could not be used.'
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, navigate]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setState('sending');
    setError('');
    try {
      await academy.requestLink(email.trim());
      setState('sent');
    } catch (err) {
      setState('error');
      setError(err instanceof ApiError ? err.message : 'Something went wrong.');
    }
  };

  return (
    <div className="relative min-h-screen pt-32 pb-20">
      <div className="hero-backdrop" />
      <div className="absolute inset-0 -z-10 bg-hero-radial" />
      <div className="container-site max-w-md">
        <div className="card p-8">
          {verifying ? (
            <div className="text-center py-6">
              <div className="animate-pulse text-cyan-400 font-mono text-sm uppercase tracking-widest">
                Signing you in…
              </div>
            </div>
          ) : state === 'sent' ? (
            <div className="text-center">
              <CheckCircle2 className="w-10 h-10 text-cyan-400 mx-auto mb-4" aria-hidden="true" />
              <h1 className="text-2xl font-bold mb-3">Check your email</h1>
              <p className="text-slate-300 leading-relaxed">
                If <strong className="text-white">{email}</strong> has access to a
                course, a sign-in link is on its way. It works once and expires in
                30 minutes.
              </p>
              <button
                type="button"
                onClick={() => setState('idle')}
                className="btn-ghost mt-6 mx-auto"
              >
                Use a different address
              </button>
            </div>
          ) : (
            <>
              <span className="eyebrow mb-5">Learner sign-in</span>
              <h1 className="text-2xl font-bold mt-3 mb-2">Welcome back</h1>
              <p className="text-slate-300 mb-6 leading-relaxed">
                Enter the email you registered or purchased with. We'll send a
                sign-in link; there's no password to remember. Inside you will
                find every course you have access to, your progress, and your
                certificates.
              </p>

              {error && (
                <p className="mb-4 text-sm text-amber-300" role="alert">
                  {error}
                </p>
              )}

              <form onSubmit={submit}>
                <label htmlFor="email" className="block text-xs font-mono uppercase tracking-widest text-slate-400 mb-2">
                  Email address
                </label>
                <div className="relative">
                  <Mail
                    className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2"
                    aria-hidden="true"
                  />
                  <input
                    id="email"
                    type="email"
                    required
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    className="w-full pl-9 pr-3 py-3 rounded-lg bg-slate-900/80 border border-slate-700 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                  />
                </div>
                <button
                  type="submit"
                  disabled={state === 'sending' || !email.trim()}
                  className="btn-primary w-full mt-5 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {state === 'sending' ? 'Sending…' : 'Email me a sign-in link'}
                  {state !== 'sending' && <ArrowRight className="w-4 h-4" aria-hidden="true" />}
                </button>
              </form>

              <p className="mt-6 text-sm text-slate-400">
                Don't have a course yet?{' '}
                <Link to="/training/micro-gas-turbine-design" className="text-cyan-400 hover:text-cyan-300">
                  See what's available
                </Link>
                .
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default SignIn;
