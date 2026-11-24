import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Check,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  KeyRound,
  RefreshCw,
} from 'lucide-react';
import { API_BASE } from '../../lib/academyApi';
import { usePageMeta } from '../../lib/meta';

type CheckoutLookup = {
  paid: boolean;
  status?: string;
  license_key?: string;
  plan?: string;
  plan_label?: string;
  email?: string;
  max_seats?: number;
  amount_cents?: number;
  currency?: string;
};

export default function Pro3DWorksWelcome() {
  usePageMeta(
    'Your Pro3DWorks v3 License Key | ProReadyEngineer',
    'Complete activation of your Pro3DWorks desktop license key.',
    { noindex: true },
  );

  const [params] = useSearchParams();
  const sessionId = params.get('session_id') ?? '';

  const [data, setData] = useState<CheckoutLookup | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [portalBusy, setPortalBusy] = useState(false);

  useEffect(() => {
    if (!sessionId || !API_BASE) return;
    let cancelled = false;
    let attempt = 0;

    async function poll() {
      while (!cancelled && attempt < 12) {
        attempt++;
        try {
          const res = await fetch(
            `${API_BASE}/api/software/checkout/${encodeURIComponent(sessionId)}`,
            { cache: 'no-store' },
          );
          if (res.ok) {
            const json = (await res.json()) as CheckoutLookup;
            if (!cancelled) setData(json);
            if (json.paid && json.license_key) return;
          }
        } catch {
          // retry transiently while webhook commits
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
      if (!cancelled && !data?.license_key) {
        setError(
          'Your payment completed, and Stripe is finishing key delivery. Check your email inbox in a minute or refresh this page.',
        );
      }
    }
    void poll();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function copyKey() {
    if (!data?.license_key) return;
    try {
      await navigator.clipboard.writeText(data.license_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  }

  async function openPortal() {
    if (!data?.license_key || !API_BASE) return;
    setPortalBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/software/billing-portal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ license_key: data.license_key }),
      });
      const json = await res.json().catch(() => ({}));
      if (res.ok && json.url) {
        window.open(String(json.url), '_blank', 'noopener');
      }
    } finally {
      setPortalBusy(false);
    }
  }

  return (
    <div className="bg-slate-950 text-slate-50 min-h-screen pt-28 pb-20">
      <div className="container-site max-w-3xl">
        <div className="card p-7 sm:p-10 bg-slate-900/80 border-slate-800">
          {!sessionId ? (
            <div className="text-center">
              <KeyRound className="w-10 h-10 text-cyan-400 mx-auto mb-3" />
              <h1 className="text-2xl font-bold text-white mb-2">
                Pro3DWorks License Activation
              </h1>
              <p className="text-slate-300 text-sm mb-6">
                No checkout session ID was found in the URL. Check your receipt email for your{' '}
                <code className="text-cyan-300">P3DW-…</code> license key or open the Customer Billing Portal on the product page.
              </p>
              <Link to="/products/pro3dworks#pricing" className="btn-primary text-sm">
                Return to Pro3DWorks
              </Link>
            </div>
          ) : data?.paid && data.license_key ? (
            <div>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs font-mono mb-4">
                <CheckCircle2 className="w-4 h-4" /> Payment Confirmed · Key Issued
              </div>
              <h1 className="font-display text-3xl sm:text-4xl font-bold text-white mb-2">
                Thank you for purchasing Pro3DWorks v3!
              </h1>
              <p className="text-slate-300 text-sm sm:text-base mb-6">
                Plan: <strong className="text-white">{data.plan_label || data.plan}</strong> · Up to{' '}
                <strong className="text-cyan-300">{data.max_seats ?? 3} workstations</strong>
                {data.email ? (
                  <>
                    {' '}
                    · Emailed copy sent to <strong className="text-white">{data.email}</strong>
                  </>
                ) : null}
              </p>

              {/* License Key Card */}
              <div className="rounded-xl bg-slate-950 border border-cyan-500/40 p-5 mb-6">
                <div className="text-xs uppercase tracking-wider text-slate-400 mb-2">
                  Your Pro3DWorks License Key
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <code className="text-xl sm:text-2xl font-mono font-bold text-cyan-300 tracking-wide select-all">
                    {data.license_key}
                  </code>
                  <button
                    type="button"
                    onClick={() => void copyKey()}
                    className="btn-primary text-sm py-2 px-4"
                  >
                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    {copied ? 'Copied!' : 'Copy Key'}
                  </button>
                </div>
              </div>

              {/* Activation Steps */}
              <div className="rounded-xl bg-slate-950/60 border border-slate-800 p-5 mb-6 space-y-3 text-sm text-slate-200">
                <h2 className="font-bold text-white">Activate in 30 seconds:</h2>
                <ol className="list-decimal list-inside space-y-1.5 text-slate-300">
                  <li>Download &amp; install Pro3DWorks v3.0.0 on Windows x64 if not already installed.</li>
                  <li>Open Pro3DWorks and click the License pill (top right) or <strong>Help → License, Trial &amp; Billing</strong>.</li>
                  <li>Paste your <code className="text-cyan-300">{data.license_key}</code> key and click <strong>Activate</strong>.</li>
                </ol>
              </div>

              <div className="flex flex-wrap gap-3">
                <a href="/download/pro3dworks-installer" className="btn-primary text-sm">
                  <Download className="w-4 h-4" /> Download Windows Installer (.exe)
                </a>
                <button
                  type="button"
                  disabled={portalBusy}
                  onClick={() => void openPortal()}
                  className="btn-secondary text-sm disabled:opacity-60"
                >
                  <ExternalLink className="w-4 h-4 text-cyan-400" />
                  {portalBusy ? 'Opening Portal…' : 'Manage Billing & Invoices'}
                </button>
                <Link to="/products/pro3dworks" className="btn-ghost text-sm px-3">
                  Product Overview →
                </Link>
              </div>
            </div>
          ) : (
            <div className="text-center py-6">
              <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-3" />
              <h1 className="text-2xl font-bold text-white mb-2">
                Confirming Stripe payment &amp; issuing your key…
              </h1>
              <p className="text-slate-300 text-sm max-w-md mx-auto">
                Hold on a moment while Stripe notifies our licensing server and generates your Ed25519 license key.
              </p>
              {error && <p className="mt-4 text-sm text-amber-300">{error}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
