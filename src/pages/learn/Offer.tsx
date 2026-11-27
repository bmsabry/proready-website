import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Lock, Tag } from 'lucide-react';
import { usePageMeta } from '../../lib/meta';
import { academy, ApiError, type CourseOfferView } from '../../lib/academyApi';

/* A private price on a course for one buyer (admin → Academy → "Sell at a
 * private price"). The token in the URL is the secret; the page shows the
 * course and the price, then hands over to Stripe Checkout, which opens with
 * the buyer's email fixed and the offer amount. */

const money = (cents: number, ccy: string) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: (ccy || 'usd').toUpperCase(),
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);

const Offer: React.FC = () => {
  const { token = '' } = useParams();
  const [offer, setOffer] = useState<CourseOfferView | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  usePageMeta('Your private price', 'A private course offer from ProReadyEngineer.', { noindex: true });

  useEffect(() => {
    let cancelled = false;
    academy
      .offer(token)
      .then((o) => !cancelled && setOffer(o))
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Could not load this offer.');
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const pay = async () => {
    setBusy(true);
    setError('');
    try {
      const { url } = await academy.offerCheckout(token);
      window.location.assign(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start checkout. Please try again.');
      setBusy(false);
    }
  };

  const until = offer
    ? new Date(offer.expires_at).toLocaleDateString(undefined, { dateStyle: 'long' })
    : '';

  return (
    <div className="relative min-h-screen pt-32 pb-20">
      <div className="hero-backdrop" />
      <div className="absolute inset-0 -z-10 bg-hero-radial" />
      <div className="container-site max-w-lg">
        <div className="card p-8">
          {!offer && !error && (
            <div className="animate-pulse text-cyan-400 font-mono text-sm uppercase tracking-widest text-center">
              Loading your offer…
            </div>
          )}

          {!offer && error && (
            <div className="text-center">
              <h1 className="text-2xl font-bold mb-3">Offer not found</h1>
              <p className="text-slate-300 leading-relaxed mb-6">{error}</p>
              <Link to="/contact" className="btn-secondary">Contact us</Link>
            </div>
          )}

          {offer && (
            <>
              <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs uppercase tracking-widest mb-3">
                <Tag className="w-4 h-4" aria-hidden="true" />
                Private offer{offer.full_name ? ` for ${offer.full_name}` : ''}
              </div>
              <h1 className="text-2xl font-bold mb-2">{offer.product.title}</h1>
              {offer.product.subtitle && (
                <p className="text-slate-400 text-sm leading-relaxed mb-6">{offer.product.subtitle}</p>
              )}

              <div className="flex items-baseline gap-3 mb-1">
                <span className="text-4xl font-bold text-white">
                  {money(offer.price_cents, offer.currency)}
                </span>
                {offer.list_price_cents > offer.price_cents && (
                  <span className="text-slate-500 line-through">
                    {money(offer.list_price_cents, offer.currency)}
                  </span>
                )}
                {offer.percent_off > 0 && (
                  <span className="text-xs font-semibold text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded px-2 py-0.5">
                    {offer.percent_off}% off
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 mb-6">
                One-time payment · lifetime access · no subscription
              </p>

              {offer.note && (
                <p className="text-sm text-slate-300 leading-relaxed border-l-2 border-cyan-500/50 pl-3 mb-6">
                  {offer.note}
                </p>
              )}

              {offer.state === 'open' ? (
                <>
                  {error && (
                    <p className="text-sm text-red-300 bg-red-950/40 border border-red-900/60 rounded-lg px-3 py-2 mb-4">
                      {error}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={pay}
                    disabled={busy}
                    className="btn-primary w-full justify-center disabled:opacity-60"
                  >
                    {busy ? 'Opening secure checkout…' : `Pay ${money(offer.price_cents, offer.currency)}`}
                  </button>
                  <p className="flex items-start gap-2 text-xs text-slate-500 mt-4 leading-relaxed">
                    <Lock className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
                    <span>
                      Secure payment by Stripe. This price is for{' '}
                      <strong className="text-slate-300">{offer.email}</strong> and is valid until{' '}
                      {until}. Your sign-in link goes to that address the moment you pay.
                    </span>
                  </p>
                </>
              ) : (
                <div className="text-sm text-amber-200 bg-amber-950/40 border border-amber-900/60 rounded-lg px-3 py-3">
                  {offer.message}
                  {offer.state === 'paid' && (
                    <>
                      {' '}
                      <Link to="/learn/signin" className="text-cyan-300 underline">
                        Sign in
                      </Link>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default Offer;
