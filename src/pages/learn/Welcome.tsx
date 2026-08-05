import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle2, Mail } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import { academy } from '../../lib/academyApi';

/* Post-purchase landing.
 *
 * Stripe redirects here before the webhook has necessarily fired, so this
 * polls the order until it flips to paid rather than asserting success it
 * cannot yet see. */

const Welcome: React.FC = () => {
  const [params] = useSearchParams();
  const sessionId = params.get('session_id') || '';
  const [status, setStatus] = useState<'checking' | 'paid' | 'slow'>('checking');
  const [email, setEmail] = useState('');

  usePageMeta('Thank you', 'Your ProReadyEngineer course purchase.', { noindex: true });

  useEffect(() => {
    if (!sessionId) {
      setStatus('slow');
      return;
    }
    let tries = 0;
    let cancelled = false;
    const tick = async () => {
      tries += 1;
      try {
        const res = await academy.checkoutStatus(sessionId);
        if (cancelled) return;
        if (res.status === 'paid') {
          setEmail(res.email || '');
          setStatus('paid');
          return;
        }
      } catch {
        /* keep polling — a cold start can lose the first request */
      }
      if (tries >= 12) setStatus('slow');
      else if (!cancelled) window.setTimeout(tick, 2500);
    };
    tick();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return (
    <div className="relative min-h-screen pt-32 pb-20">
      <div className="hero-backdrop" />
      <div className="absolute inset-0 -z-10 bg-hero-radial" />
      <div className="container-site max-w-lg text-center">
        <div className="card p-8">
          {status === 'checking' && (
            <>
              <div className="animate-pulse text-cyan-400 font-mono text-sm uppercase tracking-widest mb-4">
                Confirming your payment…
              </div>
              <p className="text-slate-400 text-sm">This usually takes a few seconds.</p>
            </>
          )}

          {status === 'paid' && (
            <>
              <CheckCircle2 className="w-12 h-12 text-cyan-400 mx-auto mb-5" aria-hidden="true" />
              <h1 className="text-2xl font-bold mb-3">You're in</h1>
              <p className="text-slate-300 leading-relaxed mb-6">
                Your access is live and it's yours for good. We've sent a sign-in
                link to <strong className="text-white">{email}</strong> — no password
                to invent.
              </p>
              <Link to="/learn/signin" className="btn-primary w-full">
                Go to your course
              </Link>
            </>
          )}

          {status === 'slow' && (
            <>
              <Mail className="w-12 h-12 text-cyan-400 mx-auto mb-5" aria-hidden="true" />
              <h1 className="text-2xl font-bold mb-3">Check your email</h1>
              <p className="text-slate-300 leading-relaxed mb-6">
                Your payment is being confirmed. As soon as it clears, a sign-in
                link lands in your inbox — usually within a minute. Nothing else
                is needed from you.
              </p>
              <Link to="/learn/signin" className="btn-secondary w-full">
                Sign in
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default Welcome;
