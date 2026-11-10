/* What to tell a person when the API refuses a request.
 *
 * The API reports a refusal in `detail`, and that is one of two shapes:
 *   - a sentence written for the reader ("Registration for this course is closed.")
 *   - for a field it rejected, a LIST of objects: [{ loc: ['body','email'], msg: '…' }]
 *
 * The list must never reach the page as-is. React cannot draw an object, and a
 * page that tried went blank: an email address without a dot (which browsers
 * accept) wiped the whole registration page. This always returns a string, and
 * for a rejected field it says which field and what to change.
 */

type FieldError = { loc?: unknown; msg?: unknown };

const fieldName = (loc: unknown): string => {
  const parts = Array.isArray(loc) ? loc.filter((p) => typeof p === 'string' && p !== 'body') : [];
  const last = (parts[parts.length - 1] as string | undefined) ?? '';
  const words = last.replace(/_/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : '';
};

const describe = (err: FieldError): string => {
  const field = fieldName(err.loc);
  const msg = typeof err.msg === 'string' ? err.msg : '';
  if (!msg) return '';
  if (/valid email address/i.test(msg)) {
    return 'Please enter a complete email address, for example name@company.com.';
  }
  let m = msg.match(/at least (\d+) character/i);
  if (m && field) return `${field} is too short (at least ${m[1]} characters).`;
  m = msg.match(/at most (\d+) character/i);
  if (m && field) return `${field} is too long (at most ${m[1]} characters).`;
  if (/^field required$/i.test(msg) && field) return `${field} is required.`;
  return field ? `${field}: ${msg}` : msg;
};

/** A readable sentence from an error response body, or `fallback`. */
export function apiErrorMessage(data: unknown, fallback: string): string {
  const body = (data ?? {}) as { detail?: unknown; error?: unknown };
  if (typeof body.detail === 'string' && body.detail.trim()) return body.detail;
  if (Array.isArray(body.detail)) {
    const lines = body.detail.map((e) => describe((e ?? {}) as FieldError)).filter(Boolean);
    // Two fields can fail for the same reason; say each thing once.
    const unique = [...new Set(lines)];
    if (unique.length) return unique.join(' ');
  }
  if (typeof body.error === 'string' && body.error.trim()) return body.error;
  return fallback;
}
