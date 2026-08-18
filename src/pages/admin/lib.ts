/**
 * Shared admin plumbing — API access, wire types, formatters, and the
 * hash <-> view-state codec used by the dashboard shell.
 *
 * Every admin page talks to the backend through api() below, which sends
 * the session cookie exactly like the old single-file dashboard did
 * (credentials: 'include', cache: 'no-store') and normalises errors:
 * a 401 throws AuthError so callers can bounce to /admin/login.
 */

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

/** For the few raw fetch() calls that bypass api() (chat widget, telemetry). */
export const fetchOpts: RequestInit = { credentials: 'include', cache: 'no-store' };

export class AuthError extends Error {
  constructor() {
    super('Not authenticated');
    this.name = 'AuthError';
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE) throw new Error('VITE_API_BASE is not configured for this build.');
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    cache: 'no-store',
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  if (res.status === 401) throw new AuthError();
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
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`);
  }
  return data as T;
}

/** Route an api() failure: AuthError -> login redirect, anything else -> setError. */
export function reportError(
  e: unknown,
  onAuthError: () => void,
  setError: (msg: string) => void,
): void {
  if (e instanceof AuthError) {
    onAuthError();
    return;
  }
  setError(e instanceof Error ? e.message : 'Request failed.');
}

// ----- Wire types ------------------------------------------------------------

export type Registration = {
  id: number;
  course_code: string;
  full_name: string;
  email: string;
  job_title: string;
  company: string;
  years_experience: string;
  location: string;
  status: 'pending' | 'paid' | 'cancelled' | string;
  /** 'paypal' | 'stripe' | '' (empty = manual invoice / not paid online) */
  payment_provider: string;
  admin_notes?: string | null;
  created_at: string;
  paid_at?: string | null;
  /** Null until they reply to a "confirm your seat" broadcast. */
  attendance_confirmed_at?: string | null;
};

export type Course = {
  code: string;
  title: string;
  start_date: string; // yyyy-mm-dd
  total_seats: number;
  status: 'open' | 'closed';
  /** Per-day schedule, Day 1 -> Day N. Length = cohort length. */
  day_dates: string[];
  /** Active seats (paid + pending) — the public counter. */
  seats_taken: number;
  seats_paid: number;
  seats_remaining: number;
  /** Online seat price in cents. 0 = invoice-only flow. */
  price_cents: number;
  currency: string;
  /** Academy product carrying this course's recorded counterpart, or null. */
  recorded_product_code: string | null;
};

export type CoursePatch = {
  title?: string;
  start_date?: string;
  total_seats?: number;
  status?: 'open' | 'closed';
  day_dates?: string[];
  price_cents?: number;
  currency?: string;
  recorded_product_code?: string | null;
};

export type RecordedStats = {
  orders_paid: number;
  revenue_cents_total: number;
  revenue_cents_30d: number;
  active_enrollments: number;
  learners_completed: number;
};

export type CourseStats = {
  code: string;
  title: string;
  start_date: string;
  status: 'open' | 'closed';
  live: {
    pending: number;
    paid: number;
    cancelled: number;
    seats_total: number;
    seats_taken: number;
    by_day: { date: string; count: number }[];
    by_company: { company: string; count: number }[];
  };
  recorded: RecordedStats | null;
};

export type SoftwareItem = {
  slug: string;
  name: string;
  blurb: string;
  asset_path: string;
  latest_version: string;
  status: 'live' | 'hidden';
  created_at: string;
  downloads: number;
  launches: number;
  usage_pings: number;
};

export type SoftwareStats = {
  slug: string;
  name: string;
  downloads: { total: number; last7: number; last30: number };
  launches: { total: number; last7: number; by_version: { version: string; count: number }[] };
  usage: { pings: number; total_minutes: number; top_features: { feature: string; count: number }[] };
};

export type AcademyProduct = {
  code: string;
  title: string;
  subtitle: string;
  status: 'draft' | 'live';
  price_cents: number;
  currency: string;
  stripe_price_id?: string;
  total_hours: number;
  module_count: number;
  lesson_count: number;
  videos_ready: number;
  videos_pending: number;
  active_enrollments: number;
};

export type Enrollment = {
  product_code: string;
  status: string;
  source: string;
  granted_at: string;
  // ACH delayed-notification tracking: 'settled' | 'pending' | 'failed'.
  settlement_status?: string;
  settlement_deadline?: string | null;
};

export type Learner = {
  id: number;
  email: string;
  full_name: string;
  status: string;
  created_at: string;
  last_login_at: string | null;
  is_owner: boolean;
  has_password: boolean;
  lessons_completed: number;
  quiz_attempts: number;
  enrollments: Enrollment[];
};

export type Owners = {
  owner_emails: string[];
  admin_email: string;
  env_var: string;
  note: string;
};

export type EmailLogRow = {
  id: number;
  ts: string;
  scope_kind: string;
  scope_code: string;
  audience: string;
  template: string;
  subject: string;
  recipient: string;
  ok: boolean;
  provider_id: string | null;
};

export type ContentLesson = {
  id: number;
  code: string;
  title: string;
  kind: string;
  body: string;
  position: number;
  duration_s: number;
  video_uid: string;
  source_file: string;
  asset_path: string;
  is_preview: boolean;
};

export type ContentModule = {
  id: number;
  code: string;
  title: string;
  position: number;
  hours: number;
  quiz_app_url: string;
  quiz_item_count: number;
  lessons: ContentLesson[];
};

export type ProductContent = {
  product: { code: string; title: string };
  modules: ContentModule[];
};

export type AuditRow = {
  id: number;
  created_at: string;
  kind: string;
  tool_name: string;
  summary: string;
  error?: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  model: string;
};


// ----- Support desk ----------------------------------------------------------

export type SupportCategory =
  | 'payment'
  | 'access'
  | 'bug'
  | 'business'
  | 'enrollment'
  | 'course_info'
  | 'software'
  | 'general';

export type SupportStatus =
  | 'new'
  | 'ai_handling'
  | 'awaiting_customer'
  | 'escalated'
  | 'auto_resolved'
  | 'resolved'
  | 'archived'
  | 'spam';

export type SupportTicket = {
  ref: string;
  subject: string;
  submitter_email: string;
  submitter_name: string;
  category: SupportCategory | string;
  category_label: string;
  priority: number;
  status: SupportStatus | string;
  source: string;
  is_spam: boolean;
  ai_attempt_count: number;
  summary: string;
  created_at: string | null;
  last_message_at: string | null;
  last_customer_message_at: string | null;
  first_responded_at: string | null;
  resolved_at: string | null;
  needs_reply: boolean;
};

export type SupportMessage = {
  id: number;
  sender_kind: 'customer' | 'ai' | 'admin' | 'note';
  sender_name: string;
  body_text: string;
  body_html: string;
  direction: string;
  email_delivered: boolean | null;
  created_at: string | null;
};

export type SupportEvent = {
  id: number;
  event_type: string;
  actor: string;
  payload: Record<string, unknown>;
  created_at: string | null;
};

/** What we know about the person who wrote in, assembled server-side. */
export type SupportCustomer = {
  email?: string;
  known?: boolean;
  learner?: { id: number; full_name: string; created_at: string | null };
  registrations?: {
    id: number;
    course_code: string;
    course_title: string;
    status: string;
    company: string;
    full_name: string;
    payment_provider: string;
    created_at: string | null;
    paid_at: string | null;
  }[];
  enrollments?: {
    product_code: string;
    product_title: string;
    status: string;
    settlement_status: string;
    granted_at: string | null;
  }[];
  orders?: {
    id: number;
    product_code: string;
    status: string;
    provider: string;
    amount_cents: number | null;
    created_at: string | null;
  }[];
  prior_tickets?: {
    ref: string;
    subject: string;
    status: string;
    category: string;
    created_at: string | null;
  }[];
};

export type SupportTicketDetail = {
  ticket: SupportTicket;
  ai_result: {
    summary?: string;
    confidence?: number;
    can_auto_resolve?: boolean;
    escalation_reason?: string;
    source?: string;
  };
  meta: Record<string, unknown>;
  messages: SupportMessage[];
  events: SupportEvent[];
  customer: SupportCustomer;
};

export type SupportStats = {
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  open: number;
  needs_human: number;
  total: number;
};

export type SupportDraft = {
  ok: boolean;
  reply_html: string;
  needs_from_admin: string[];
  suggested_status: string;
};

export type SupportSettings = {
  api_url: string;
  model_name: string;
  api_key_masked: string;
  kb_text: string;
  is_configured: boolean;
  using_own_credentials: boolean;
  llm_available: boolean;
  categories: {
    key: string;
    label: string;
    priority: number;
    auto: boolean;
    description: string;
  }[];
};

/** Human labels for the ticket lifecycle, used by the inbox and the thread. */
export const SUPPORT_STATUS_LABEL: Record<string, string> = {
  new: 'New',
  ai_handling: 'AI triaging',
  awaiting_customer: 'Awaiting customer',
  escalated: 'Needs you',
  auto_resolved: 'Auto-resolved',
  resolved: 'Resolved',
  archived: 'Archived',
  spam: 'Spam',
};

export type NotifyAudience = 'all' | 'paid' | 'pending' | 'recorded' | 'everyone';

export type NotifyResult = {
  ok: boolean;
  recipients: number;
  failures: number;
  failed_addresses?: string[];
};

// ----- View state <-> URL hash ----------------------------------------------

export type CourseTab =
  | 'registrations'
  | 'buyers'
  | 'access'
  | 'integrity'
  | 'comms'
  | 'stats'
  | 'materials'
  | 'settings';

export const COURSE_TABS: CourseTab[] = [
  'registrations',
  'buyers',
  'access',
  'integrity',
  'comms',
  'stats',
  'materials',
  'settings',
];

export type ViewState =
  | { page: 'overview' }
  | { page: 'courses'; course?: string; tab?: CourseTab }
  | { page: 'academy' }
  | { page: 'software'; slug?: string }
  | { page: 'comms' }
  | { page: 'support'; ref?: string }
  | { page: 'ai' };

export function hashFor(v: ViewState): string {
  switch (v.page) {
    case 'courses':
      return v.course
        ? `#courses/${encodeURIComponent(v.course)}/${v.tab ?? 'registrations'}`
        : '#courses';
    case 'software':
      return v.slug ? `#software/${encodeURIComponent(v.slug)}` : '#software';
    case 'academy':
      return '#academy';
    case 'comms':
      return '#comms';
    case 'support':
      return v.ref ? `#support/${encodeURIComponent(v.ref)}` : '#support';
    case 'ai':
      return '#ai';
    default:
      return '#overview';
  }
}

export function parseHash(raw: string): ViewState {
  const parts = raw
    .replace(/^#\/?/, '')
    .split('/')
    .filter(Boolean)
    .map((p) => {
      try {
        return decodeURIComponent(p);
      } catch {
        return p;
      }
    });
  const [page, a, b] = parts;
  switch (page) {
    case 'courses':
      if (!a) return { page: 'courses' };
      return {
        page: 'courses',
        course: a,
        tab: COURSE_TABS.includes(b as CourseTab) ? (b as CourseTab) : 'registrations',
      };
    case 'software':
      return a ? { page: 'software', slug: a } : { page: 'software' };
    case 'academy':
      return { page: 'academy' };
    case 'comms':
      return { page: 'comms' };
    case 'support':
      return a ? { page: 'support', ref: a } : { page: 'support' };
    case 'ai':
      return { page: 'ai' };
    default:
      return { page: 'overview' };
  }
}

// ----- Formatters ------------------------------------------------------------

/** "Jun 3, 2026, 2:14 PM" — timestamps (registrations, email log, telemetry). */
export function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

/** "Jun 3, 2026" — date-only fields (start_date, day_dates). */
export function formatDay(iso: string): string {
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' });
  } catch {
    return iso;
  }
}

/** Money from cents. Whole amounts drop the decimals ("$450"), odd cents keep them. */
export function money(cents: number, ccy = 'usd'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: ccy.toUpperCase(),
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

export function fmtInt(n: number): string {
  return n.toLocaleString();
}

/** Seconds -> "1h 04m" / "12m 05s" / "45s". */
export function fmtDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, '0')}s`;
  return `${sec}s`;
}

/**
 * Convert plain-text email body into safe HTML for email rendering.
 *
 * - Escapes HTML entities so user-typed '<' and '&' don't break the markup.
 * - Splits on blank lines into <p> paragraphs.
 * - Single newlines within a paragraph become <br>.
 * - Bare http(s)/mailto links auto-link so the recipient can click.
 */
export function plainTextToEmailHtml(text: string): string {
  const escape = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const linkify = (s: string) =>
    s.replace(
      /(https?:\/\/[^\s<]+|mailto:[^\s<]+)/g,
      (url) => `<a href="${url}" style="color:#22d3ee;">${url}</a>`,
    );

  const paragraphs = text.replace(/\r\n/g, '\n').split(/\n{2,}/);
  return paragraphs
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
    .map((p) => {
      const escaped = escape(p).replace(/\n/g, '<br>');
      return `<p style="margin:0 0 16px;">${linkify(escaped)}</p>`;
    })
    .join('\n');
}

/** Build a CSV in the browser and trigger a download (BOM so Excel opens it clean). */
export function downloadCsv(
  filename: string,
  header: string[],
  rows: (string | number | null | undefined)[][],
): void {
  const esc = (v: string | number | null | undefined) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [header, ...rows].map((r) => r.map(esc).join(',')).join('\r\n');
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** "US" -> "United States" via the browser's own region names; falls back to the code. */
const regionNames = typeof Intl !== 'undefined' ? new Intl.DisplayNames(['en'], { type: 'region' }) : null;
export function countryName(code: string): string {
  if (!code) return code;
  try {
    return regionNames?.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}
