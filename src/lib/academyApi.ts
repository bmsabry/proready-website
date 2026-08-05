/* Client for the academy API.
 *
 * Every call is credentialed — the learner session is an httpOnly cookie set
 * by the API on a different origin, so `credentials: 'include'` is required
 * on all of them, not just the authenticated ones (the catalog endpoint uses
 * it to report whether you already own the course).
 */

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE) {
    throw new ApiError(0, 'The learning platform is not configured yet.');
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    });
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check your connection.');
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new ApiError(res.status, data?.detail || `Request failed (${res.status})`);
  }
  return data as T;
}

/* ---------- types ---------- */

export type Me = {
  signed_in: boolean;
  email?: string;
  full_name?: string;
  /* Owner accounts see every module regardless of purchase or publish state. */
  is_owner?: boolean;
  /* False until they set the password the interactive modules sign in with. */
  has_password?: boolean;
  enrollments?: { product_code: string; title: string; granted_at: string }[];
};

export type LessonSummary = {
  id: number;
  code: string;
  title: string;
  kind: 'video' | 'slides' | 'reading' | 'lab' | 'calculator' | 'quiz';
  position: number;
  duration_s: number;
  is_preview: boolean;
  playable: boolean;
  accessible: boolean;
  position_s: number;
  watched_s: number;
  completed: boolean;
};

export type ModuleState = {
  id: number;
  code: string;
  title: string;
  summary: string;
  position: number;
  hours: number;
  objectives: string[];
  topics: string[];
  quiz_app_url: string;
  unlocked: boolean;
  lesson_count: number;
  lessons_completed: number;
  duration_s: number;
  watched_s: number;
  percent: number;
  has_formative: boolean;
  has_summative: boolean;
  formative_score: number | null;
  formative_passed: boolean;
  summative_score: number | null;
  summative_passed: boolean;
  mastery_threshold: number;
  lessons: LessonSummary[];
};

export type CourseState = {
  product: { code: string; title: string; subtitle: string; total_hours: number };
  modules: ModuleState[];
  percent: number;
  lessons_completed: number;
  lessons_total: number;
  complete: boolean;
  certificate_code: string | null;
  video_ready: boolean;
};

export type LessonDetail = {
  id: number;
  code: string;
  title: string;
  kind: LessonSummary['kind'];
  duration_s: number;
  body: string;
  asset_path: string;
  is_preview: boolean;
  module: { id: number | null; code: string; title: string; product_code: string };
  playback: { hls: string; dash: string; thumbnail: string; iframe: string; expires_in: number } | null;
  video_pending: boolean;
  progress: { position_s: number; watched_s: number; completed: boolean };
  prev_lesson_id: number | null;
  next_lesson_id: number | null;
  watermark: string;
};

export type QuizItem = {
  code: string;
  kind: 'mcq' | 'numeric' | 'short' | 'match';
  stem: string;
  options: { key: string; text: string }[];
  cognitive_level: string;
  position: number;
  section: number;
  rubric: string;
};

export type QuizSet = {
  module: { id: number; code: string; title: string };
  item_set: 'formative' | 'summative';
  threshold: number;
  items: QuizItem[];
  best_score: number | null;
  passed: boolean;
};

export type QuizResult = {
  score_pct: number;
  passed: boolean;
  auto_correct: number;
  auto_total: number;
  threshold: number;
  feedback: {
    code: string;
    correct: boolean | null;
    response: unknown;
    explanation: string;
    rubric: string;
    needs_review: boolean;
  }[];
};

/* ---------- endpoints ---------- */

export const academy = {
  me: () => request<Me>('/api/academy/me'),

  requestLink: (email: string, nextPath = '/learn') =>
    request<{ ok: boolean }>('/api/academy/auth/request-link', {
      method: 'POST',
      body: JSON.stringify({ email, next_path: nextPath, website: '' }),
    }),

  verify: (token: string) =>
    request<{ ok: boolean; email: string; next_path: string }>(
      '/api/academy/auth/verify',
      { method: 'POST', body: JSON.stringify({ token }) }
    ),

  logout: () =>
    request<{ ok: boolean }>('/api/academy/auth/logout', { method: 'POST' }),

  setPassword: (password: string) =>
    request<{ ok: boolean }>('/api/academy/auth/set-password', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),

  course: (code: string) => request<CourseState>(`/api/academy/course/${code}`),

  lesson: (id: number) => request<LessonDetail>(`/api/academy/lesson/${id}`),

  heartbeat: (id: number, positionS: number, watchedDeltaS: number) =>
    request<{ ok: boolean; watched_s: number; completed: boolean }>(
      `/api/academy/lesson/${id}/progress`,
      {
        method: 'POST',
        body: JSON.stringify({
          position_s: Math.max(0, Math.round(positionS)),
          // The API clamps this to 60s per beat; clamp here too so an
          // idle tab that wakes up late doesn't send a rejected value.
          watched_delta_s: Math.max(0, Math.min(60, Math.round(watchedDeltaS))),
        }),
      }
    ),

  quiz: (moduleId: number, set: 'formative' | 'summative') =>
    request<QuizSet>(`/api/academy/quiz/${moduleId}/${set}`),

  submitQuiz: (
    moduleId: number,
    set: 'formative' | 'summative',
    responses: Record<string, unknown>
  ) =>
    request<QuizResult>(`/api/academy/quiz/${moduleId}/${set}`, {
      method: 'POST',
      body: JSON.stringify({ responses }),
    }),

  certificate: (code: string) =>
    request<{ code: string; learner_name: string; issued_at: string }>(
      `/api/academy/certificate/${code}`,
      { method: 'POST' }
    ),

  checkoutStatus: (sessionId: string) =>
    request<{ status: string; product_code: string; email: string }>(
      `/api/academy/checkout/${sessionId}`
    ),
};

export function formatDuration(seconds: number): string {
  if (!seconds) return '';
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m} min`;
}
