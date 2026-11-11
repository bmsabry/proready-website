/* Client for the public AI assistant (/api/chat).
 *
 * The server answers every conversational outcome with HTTP 200 and a
 * `status`, plus the sentence to show: the widget never interprets an HTTP
 * error code. Nothing in this file (or anywhere in the bundle) states a
 * price; the assistant itself is not allowed to either.
 */

import { apiErrorMessage } from './apiError';

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

/** ok: answered. limit: today's messages are used up. banned: shut out.
 *  unavailable: the assistant is off for now (daily budget, or not set up).
 *  disabled: switched off by the owner. error: no answer this time; the
 *  message did not count and can be sent again. */
export type ChatStatus = 'ok' | 'limit' | 'banned' | 'unavailable' | 'disabled' | 'error';

export type ChatStatusOut = {
  enabled: boolean;
  status: ChatStatus;
  remaining: number;
  limit: number;
  max_chars: number;
  disclosure: string;
  book_url: string;
  /** The sentence to show for any status other than ok. */
  message: string;
};

export type ChatReply = {
  status: ChatStatus;
  reply: string;
  conversation_id: string;
  remaining: number;
  limit: number;
  book_url: string;
};

export class ChatError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ChatError';
  }
}

const UNREACHABLE = 'Could not reach the assistant. Please check your connection and try again.';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE) throw new ChatError(0, 'The assistant is not available on this site yet.');
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/chat${path}`, {
      credentials: 'include',
      cache: 'no-store',
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    });
  } catch {
    throw new ChatError(0, UNREACHABLE);
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
    throw new ChatError(
      res.status,
      apiErrorMessage(data, 'The assistant could not take that message. Please try again.'),
    );
  }
  return data as T;
}

export const chatApi = {
  status: () => request<ChatStatusOut>('/status'),
  send: (message: string, conversationId: string, page: string) =>
    request<ChatReply>('', {
      method: 'POST',
      body: JSON.stringify({ message, conversation_id: conversationId, page }),
    }),
};

/** Site paths the assistant must never appear on. */
const HIDDEN_PREFIXES = ['/learn', '/admin', '/verify', '/consult/booking'];

export function chatAllowedOn(pathname: string): boolean {
  const p = pathname.replace(/\/+$/, '') || '/';
  return !HIDDEN_PREFIXES.some((pre) => p === pre || p.startsWith(`${pre}/`));
}
