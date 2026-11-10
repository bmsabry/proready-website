import React, { useId, useState } from 'react';

/* "Leave your email and we'll tell you" — one small form, used wherever the
 * site collects interest: a course that is not open yet, the next cohort of a
 * course whose current one is full or already running, and the research
 * newsletter.
 *
 * Every address goes to POST /api/interest under a `slug`. Each slug is its
 * own list in Admin → Courses → Waitlists, and a broadcast can be sent to one
 * list from there.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? '';

type Props = {
  /** The list this address joins (lowercase letters, digits and hyphens). */
  slug: string;
  /** What the email box is for, read out by screen readers. */
  label: string;
  /** Shown in place of the form once the address is saved. */
  doneText: string;
  button?: string;
  /** 'compact' sits at the foot of a card; 'roomy' stands on its own. */
  size?: 'compact' | 'roomy';
  className?: string;
};

const NotifyMeForm = ({
  slug,
  label,
  doneText,
  button = 'Notify me',
  size = 'compact',
  className = '',
}: Props) => {
  const [email, setEmail] = useState('');
  const [website, setWebsite] = useState(''); // honeypot: people never see or fill it
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'invalid' | 'failed'>('idle');
  const inputId = useId();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (state === 'busy') return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setState('invalid');
      return;
    }
    setState('busy');
    try {
      const res = await fetch(`${API_BASE}/api/interest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course_slug: slug, email: email.trim(), website }),
      });
      setState(res.ok ? 'done' : res.status === 422 ? 'invalid' : 'failed');
    } catch {
      setState('failed');
    }
  };

  if (state === 'done') {
    return (
      <p role="status" className={`text-sm text-cyan-300 ${className}`}>
        {doneText}
      </p>
    );
  }

  const roomy = size === 'roomy';
  return (
    <form onSubmit={submit} noValidate className={`flex flex-wrap gap-2 ${className}`}>
      <label className="sr-only" htmlFor={inputId}>
        {label}
      </label>
      <input
        id={inputId}
        name="email"
        type="email"
        required
        autoComplete="email"
        value={email}
        onChange={(e) => {
          setEmail(e.target.value);
          if (state !== 'idle') setState('idle');
        }}
        aria-invalid={state === 'invalid'}
        aria-describedby={state === 'invalid' || state === 'failed' ? `${inputId}-msg` : undefined}
        placeholder="you@company.com"
        className={`flex-1 min-w-0 bg-slate-900/60 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-400 focus:outline-none focus:border-cyan-400 transition-colors ${
          roomy ? 'px-4 py-3' : 'px-3 py-2'
        }`}
      />
      <input
        type="text"
        name="website"
        value={website}
        onChange={(e) => setWebsite(e.target.value)}
        className="hidden"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
      />
      <button
        type="submit"
        disabled={state === 'busy'}
        className={
          roomy
            ? 'btn-primary whitespace-nowrap disabled:opacity-60'
            : 'btn-secondary px-4 py-2 text-sm whitespace-nowrap disabled:opacity-60'
        }
      >
        {state === 'busy' ? 'Adding…' : button}
      </button>
      {(state === 'invalid' || state === 'failed') && (
        <p id={`${inputId}-msg`} role="alert" className="basis-full text-xs text-amber-300">
          {state === 'invalid'
            ? 'Please enter a complete email address, for example name@company.com.'
            : 'That did not go through. Please try again, or email info@proreadyengineer.com.'}
        </p>
      )}
    </form>
  );
};

export default NotifyMeForm;
