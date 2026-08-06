import React, { useEffect, useRef, useState } from 'react';

/* ---------------------------------------------------------------------------
   PayPal Smart Buttons wrapper.

   Loads the official PayPal JS SDK once (idempotent script injection) using
   the client id from GET /api/payments/config, then renders the buttons into
   a plain div. The page owns the money flow: `createOrder` must return a
   PayPal order id from our backend, `onApprove` must capture it there.

   Renders nothing when PayPal is not configured (config says
   paypal_enabled=false) or when the SDK fails to load — pages fall back to
   their card / invoice paths.
--------------------------------------------------------------------------- */

/* Minimal typing for the slice of the PayPal SDK we use. */
interface PayPalButtonsInstance {
  render: (container: HTMLElement) => Promise<void>;
  close?: () => Promise<void>;
}
interface PayPalNamespace {
  Buttons: (options: {
    style?: {
      layout?: 'vertical' | 'horizontal';
      shape?: 'rect' | 'pill';
      label?: 'paypal' | 'pay' | 'checkout' | 'buynow';
      tagline?: boolean;
    };
    createOrder: () => Promise<string>;
    onApprove: (data: { orderID: string }) => Promise<void>;
    onError?: (err: unknown) => void;
  }) => PayPalButtonsInstance;
}
declare global {
  interface Window {
    paypal?: PayPalNamespace;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

export type PaymentsConfig = {
  paypal_enabled: boolean;
  paypal_client_id: string;
  paypal_mode: string;
  currency: string;
  stripe_enabled: boolean;
};

const DISABLED_CONFIG: PaymentsConfig = {
  paypal_enabled: false,
  paypal_client_id: '',
  paypal_mode: 'sandbox',
  currency: 'usd',
  stripe_enabled: false,
};

let configPromise: Promise<PaymentsConfig> | null = null;

/** GET /api/payments/config, cached for the page lifetime and shared by every
    caller. Never rejects — resolves to an all-disabled config when the API is
    unreachable, so payment UI simply stays hidden. */
export function fetchPaymentsConfig(): Promise<PaymentsConfig> {
  if (!API_BASE) return Promise.resolve(DISABLED_CONFIG);
  if (!configPromise) {
    configPromise = fetch(`${API_BASE}/api/payments/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => (d ? { ...DISABLED_CONFIG, ...d } : DISABLED_CONFIG))
      .catch(() => DISABLED_CONFIG);
  }
  return configPromise;
}

let sdkPromise: Promise<PayPalNamespace | null> | null = null;

/** Inject the PayPal JS SDK exactly once. Resolves null (after a
    console.warn) on load failure so callers can hide themselves. */
function loadPayPalSdk(clientId: string, currency: string): Promise<PayPalNamespace | null> {
  if (typeof window === 'undefined') return Promise.resolve(null);
  if (window.paypal) return Promise.resolve(window.paypal);
  if (!sdkPromise) {
    sdkPromise = new Promise((resolve) => {
      const existing = document.querySelector<HTMLScriptElement>('script[data-paypal-sdk]');
      const script = existing ?? document.createElement('script');
      script.addEventListener('load', () => resolve(window.paypal ?? null));
      script.addEventListener('error', () => {
        console.warn('PayPal SDK failed to load; PayPal buttons hidden.');
        resolve(null);
      });
      if (!existing) {
        script.src =
          `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(clientId)}` +
          `&currency=${encodeURIComponent(currency.toUpperCase())}&intent=capture`;
        script.async = true;
        script.dataset.paypalSdk = 'true';
        document.head.appendChild(script);
      }
    });
  }
  return sdkPromise;
}

const PayPalButtons = ({
  createOrder,
  onApprove,
  disabled = false,
}: {
  /** Ask our backend to create a PayPal order; resolve with the order id. */
  createOrder: () => Promise<string>;
  /** Capture the approved order on our backend. */
  onApprove: (orderId: string) => Promise<void>;
  disabled?: boolean;
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'hidden'>('loading');

  // The SDK captures its callbacks once at Buttons() time; route them through
  // a ref so they always see the page's latest state without re-rendering.
  const cbRef = useRef({ createOrder, onApprove });
  cbRef.current = { createOrder, onApprove };

  useEffect(() => {
    let cancelled = false;
    let buttons: PayPalButtonsInstance | null = null;
    (async () => {
      const cfg = await fetchPaymentsConfig();
      if (cancelled) return;
      if (!cfg.paypal_enabled || !cfg.paypal_client_id) {
        setState('hidden');
        return;
      }
      const paypal = await loadPayPalSdk(cfg.paypal_client_id, cfg.currency);
      if (cancelled) return;
      if (!paypal || !containerRef.current) {
        setState('hidden');
        return;
      }
      try {
        buttons = paypal.Buttons({
          style: { layout: 'vertical', shape: 'rect', label: 'paypal', tagline: false },
          createOrder: () => cbRef.current.createOrder(),
          onApprove: (data) => cbRef.current.onApprove(data.orderID),
          onError: (err) => console.warn('PayPal checkout error:', err),
        });
        await buttons.render(containerRef.current);
        if (!cancelled) setState('ready');
      } catch (err) {
        console.warn('PayPal buttons could not render:', err);
        if (!cancelled) setState('hidden');
      }
    })();
    return () => {
      cancelled = true;
      buttons?.close?.().catch(() => {});
    };
  }, []);

  if (state === 'hidden') return null;

  return (
    <div
      ref={containerRef}
      className={disabled ? 'pointer-events-none opacity-40 transition-opacity' : 'transition-opacity'}
      aria-disabled={disabled || undefined}
    />
  );
};

export default PayPalButtons;
