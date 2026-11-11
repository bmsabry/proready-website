/* Client for the public consulting-booking API (/api/consult).
 *
 * The wire shapes below follow the API contract in the consulting spec.
 * Prices exist ONLY in the quote and booking responses: the availability
 * response carries an urgency tier, never an amount, and nothing in this
 * file (or anywhere in the bundle) hard-codes a rate. Every amount the
 * visitor sees comes from the server at the moment they ask for a quote.
 */

import { apiErrorMessage } from './apiError';

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

export type Tier = 'same_day' | 'next_day' | 'priority' | 'standard';

export type Slot = { start: string; max_minutes: number; tier: Tier };
export type AvailabilityDay = { date: string; slots: Slot[] };

export type Availability = {
  enabled: boolean;
  business_timezone: string;
  step_minutes: number;
  durations: number[];
  days: AvailabilityDay[];
  next_available: { start: string; tier: Tier } | null;
};

export type Quote = {
  start: string;
  minutes: number;
  tier: Tier;
  tier_label: string;
  rate_cents_per_hour: number;
  total_cents: number;
  fee_percent: number;
  fee_cents: number;
  free_cancel_until: string | null;
  hold_at: string;
  terms_version: string;
  terms: string[];
};

export type BookRequest = {
  start: string;
  minutes: number;
  full_name: string;
  email: string;
  company?: string;
  phone?: string;
  topic: string;
  timezone: string;
  terms_version: string;
  agree: true;
  website: string;
};

export type BookResponse = { ref: string; manage_token: string; checkout_url: string };

export type BookingStatus =
  | 'pending_card'
  | 'confirmed'
  | 'cancelled'
  | 'completed'
  | 'no_show'
  | 'expired';

export type BookingView = {
  ref: string;
  status: BookingStatus;
  start: string;
  minutes: number;
  timezone: string;
  tier_label: string;
  total_cents: number;
  fee_cents: number;
  free_cancel_until: string | null;
  meet_url: string | null;
  can_cancel: boolean;
  cancel_fee_cents: number;
  charged_cents: number | null;
  card_brand: string | null;
  card_last4: string | null;
  /** POST /booking/{ref}/card will be accepted now (continue to card entry, or replace the card). */
  can_replace_card?: boolean;
  /** The card on file was refused (for the hold or a charge) and money is still expected. */
  card_problem?: boolean;
};

/** A refusal from the API, with its HTTP status (0 = never reached it). */
export class ConsultError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ConsultError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE) throw new ConsultError(0, 'Booking is not configured on this site yet.');
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/consult${path}`, {
      credentials: 'include',
      cache: 'no-store',
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    });
  } catch {
    throw new ConsultError(0, 'Could not reach the booking service. Please check your connection and try again.');
  }
  const text = await res.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = {};
    }
  }
  if (!res.ok) {
    const fallback =
      res.status === 429
        ? 'Too many requests in a short time. Please wait a minute and try again.'
        : `The booking service could not complete this request (${res.status}). Please try again.`;
    throw new ConsultError(res.status, apiErrorMessage(data, fallback));
  }
  return data as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });

export const consult = {
  availability: (tz: string) => request<Availability>(`/availability?tz=${encodeURIComponent(tz)}`),
  quote: (start: string, minutes: number) => post<Quote>('/quote', { start, minutes }),
  book: (body: BookRequest) => post<BookResponse>('/book', body),
  booking: (ref: string, t: string) =>
    request<BookingView>(`/booking/${encodeURIComponent(ref)}?t=${encodeURIComponent(t)}`),
  cancel: (ref: string, t: string) => post<BookingView>(`/booking/${encodeURIComponent(ref)}/cancel`, { t }),
  card: (ref: string, t: string) => post<{ checkout_url: string }>(`/booking/${encodeURIComponent(ref)}/card`, { t }),
};

// ----- Presentation helpers ---------------------------------------------------

/** Urgency as words. Never an amount: rates only come from a quote. */
export const TIER_LABEL: Record<Tier, string> = {
  same_day: 'Same day',
  next_day: 'Next day',
  priority: 'Priority',
  standard: 'Standard',
};

export const TIER_HINT: Record<Tier, string> = {
  same_day: 'Today',
  next_day: 'Tomorrow',
  priority: 'Within the week',
  standard: 'A week or more ahead',
};

export const tierLabel = (t: string): string => TIER_LABEL[t as Tier] ?? t;

/** The visitor's own IANA zone, or New York when the browser will not say. */
export function visitorTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/New_York';
  } catch {
    return 'America/New_York';
  }
}

/** True when the browser knows this IANA zone. */
export function isTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** "3:30 PM" in the given zone. */
export function fmtTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { timeZone: tz, hour: 'numeric', minute: '2-digit' });
}

/** "Tuesday, November 10, 2026, 3:30 PM EST" in the given zone. */
export function fmtDateTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleString('en-US', {
    timeZone: tz,
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

/** "Tue, Nov 10, 3:30 PM EST": the compact form for one-line summaries. */
export function fmtShortDateTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleString('en-US', {
    timeZone: tz,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

/** A "YYYY-MM-DD" calendar date as words, read as that date (no zone shift). */
export function fmtDay(date: string, style: 'long' | 'short' = 'long'): string {
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(Date.UTC(y, (m || 1) - 1, d || 1, 12));
  return dt.toLocaleDateString('en-US', {
    timeZone: 'UTC',
    weekday: style === 'long' ? 'long' : 'short',
    month: style === 'long' ? 'long' : 'short',
    day: 'numeric',
  });
}

/** Short zone name, e.g. "EST" or "GMT+4", for a moment in a zone. */
export function zoneAbbr(iso: string, tz: string): string {
  try {
    const part = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' })
      .formatToParts(new Date(iso))
      .find((p) => p.type === 'timeZoneName');
    return part?.value ?? tz;
  } catch {
    return tz;
  }
}

/** Amount from cents in US dollars; whole amounts drop the decimals. */
export function usd(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

/** "30 minutes", "1 hour", "1 hour 30 minutes", "2 hours". */
export function fmtMinutes(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  const hs = h ? `${h} hour${h === 1 ? '' : 's'}` : '';
  const ms = m ? `${m} minutes` : '';
  return [hs, ms].filter(Boolean).join(' ') || '0 minutes';
}

/** Every IANA zone the browser knows, the visitor's own first. */
export function timeZoneOptions(own: string): string[] {
  let all: string[] = [];
  try {
    const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
    all = fn ? fn('timeZone') : [];
  } catch {
    all = [];
  }
  if (all.length === 0) {
    all = [
      'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
      'America/Toronto', 'America/Sao_Paulo', 'Europe/London', 'Europe/Paris', 'Europe/Berlin',
      'Africa/Cairo', 'Asia/Riyadh', 'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore',
      'Asia/Tokyo', 'Australia/Sydney', 'UTC',
    ];
  }
  return [own, ...all.filter((z) => z !== own)];
}
