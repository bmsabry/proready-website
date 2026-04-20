import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Lock, LogIn, AlertCircle } from 'lucide-react';

// Same env var as the training page's form. Set in Cloudflare Pages env.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

export default function AdminLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  // If we already have a valid cookie, skip the form and go to the dashboard.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!API_BASE) {
        if (!cancelled) setCheckingSession(false);
        return;
      }
      try {
        const res = await fetch(`${API_BASE}/api/admin/me`, {
          credentials: 'include',
          cache: 'no-store',
        });
        if (!cancelled && res.ok) navigate('/admin', { replace: true });
      } catch {
        /* ignore — stay on login form */
      } finally {
        if (!cancelled) setCheckingSession(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!API_BASE) {
      setError('Admin login is not configured (VITE_API_BASE missing).');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({} as any));
        setError(body.detail ?? `Login failed (HTTP ${res.status}).`);
        setLoading(false);
        return;
      }
      navigate('/admin', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
      setLoading(false);
    }
  }

  if (checkingSession) {
    return (
      <section className="min-h-[70vh] flex items-center justify-center bg-slate-950 text-slate-300">
        <div className="animate-pulse">Checking session…</div>
      </section>
    );
  }

  return (
    <section className="min-h-[80vh] flex items-center justify-center bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 py-16 px-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="w-full max-w-md bg-slate-900/70 border border-slate-800 rounded-2xl p-8 shadow-xl shadow-cyan-950/20"
      >
        <div className="flex items-center gap-3 mb-6">
          <div className="w-11 h-11 rounded-xl bg-cyan-600/20 flex items-center justify-center">
            <Lock className="w-5 h-5 text-cyan-300" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">Admin sign-in</h1>
            <p className="text-sm text-slate-400">ProReadyEngineer training dashboard</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm text-slate-300 mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 focus:border-cyan-500 focus:outline-none text-white placeholder-slate-500"
              placeholder="you@proreadyengineer.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm text-slate-300 mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 focus:border-cyan-500 focus:outline-none text-white"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 text-sm text-red-300 bg-red-950/40 border border-red-900/60 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <LogIn className="w-4 h-4" />
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="text-xs text-slate-500 mt-6 leading-relaxed">
          Access is restricted to the configured admin email. Sessions last 7 days and are
          kept in a signed, httpOnly cookie.
        </p>
      </motion.div>
    </section>
  );
}
