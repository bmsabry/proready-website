import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Award,
  BadgeCheck,
  CalendarClock,
  Check,
  ClipboardCheck,
  Copy,
  CreditCard,
  Download,
  ExternalLink,
  Linkedin,
  MailQuestion,
  ShieldCheck,
  Video,
} from 'lucide-react';
import {
  academy,
  ApiError,
  certificateFileUrl,
  CertificationStatus,
  CompetencyScore,
  IssuedCertificate,
} from '../../lib/academyApi';

/* Certification panel — both tiers, on the course dashboard.
 *
 * Tier 1 issues itself: the API re-checks completion every time this panel
 * loads and after every quiz/heartbeat, so the panel only ever has to show
 * the state. The one thing it must collect is the learner's name.
 *
 * Tier 2 is a strict state machine on the server; this panel renders the
 * current step and offers exactly the action that step allows. */

const fmtDate = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '';

const money = (cents: number, currency: string) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
    maximumFractionDigits: 0,
  }).format(cents / 100);

const CopyLink = ({ text }: { text: string }) => {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn-ghost text-sm py-2 px-3"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          window.setTimeout(() => setDone(false), 2000);
        } catch {
          /* clipboard blocked — the link is visible on screen anyway */
        }
      }}
    >
      {done ? <Check className="w-4 h-4" aria-hidden="true" /> : <Copy className="w-4 h-4" aria-hidden="true" />}
      {done ? 'Copied' : 'Copy verification link'}
    </button>
  );
};

/* The issued-credential block, shared by both tiers. */
const CertificateCard = ({ cert }: { cert: IssuedCertificate }) => (
  <div className="grid md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-6 items-start">
    <a
      href={certificateFileUrl(cert.code, 'pdf')}
      target="_blank"
      rel="noopener"
      className="block rounded-lg overflow-hidden border border-slate-700/70 bg-white shadow-glow-cyan"
      aria-label={`Open your ${cert.title} as a PDF`}
    >
      {cert.preview_url ? (
        <img
          src={certificateFileUrl(cert.code, 'png')}
          alt={`${cert.title} issued to ${cert.learner_name}`}
          className="w-full h-auto block"
          loading="lazy"
        />
      ) : (
        <div className="aspect-[11/8.5] flex items-center justify-center text-slate-500 text-sm">
          Preview unavailable. Open the PDF
        </div>
      )}
    </a>
    <div>
      <div className="text-xs font-mono uppercase tracking-widest text-cyan-400">
        Issued {fmtDate(cert.issued_at)}
        {cert.exam_date ? ` · examined ${fmtDate(cert.exam_date)}` : ''}
      </div>
      <h3 className="text-lg font-semibold text-white mt-1">{cert.title}</h3>
      <p className="text-sm text-slate-300 mt-1">
        Issued to <span className="text-white">{cert.learner_name}</span>
      </p>
      <dl className="mt-3 text-xs text-slate-400 space-y-1">
        <div className="flex gap-2">
          <dt className="w-24 shrink-0">Credential ID</dt>
          <dd className="font-mono text-slate-200">{cert.code}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-24 shrink-0">Verify at</dt>
          <dd>
            <a href={cert.verify_url} className="text-cyan-400 hover:text-cyan-300 underline-offset-2 hover:underline" target="_blank" rel="noopener">
              {cert.verify_url.replace(/^https?:\/\//, '')}
            </a>
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-24 shrink-0">Signature</dt>
          <dd className="font-mono text-slate-300">{cert.signature_fingerprint}</dd>
        </div>
      </dl>
      <div className="flex flex-wrap gap-2 mt-4">
        <a
          href={certificateFileUrl(cert.code, 'pdf')}
          className="btn-primary text-sm py-2 px-4"
          target="_blank"
          rel="noopener"
        >
          <Download className="w-4 h-4" aria-hidden="true" /> Download PDF
        </a>
        <a
          href={cert.linkedin.add_to_profile}
          className="btn-secondary text-sm py-2 px-4"
          target="_blank"
          rel="noopener"
        >
          <Linkedin className="w-4 h-4" aria-hidden="true" /> Add to LinkedIn profile
        </a>
        <a
          href={cert.linkedin.share}
          className="btn-secondary text-sm py-2 px-4"
          target="_blank"
          rel="noopener"
        >
          <ExternalLink className="w-4 h-4" aria-hidden="true" /> Share on LinkedIn
        </a>
        <CopyLink text={cert.verify_url} />
      </div>
      <p className="text-xs text-slate-500 mt-3">
        "Add to profile" opens LinkedIn's Licenses &amp; Certifications form pre-filled. "Share"
        posts the verification page, which shows the certificate itself.
      </p>
    </div>
  </div>
);

const NameForm = ({
  initial,
  onSaved,
}: {
  initial: string;
  onSaved: (name: string) => void;
}) => {
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <form
      className="mt-4 flex flex-col sm:flex-row gap-3 sm:items-end"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError('');
        try {
          const res = await academy.setName(name);
          onSaved(res.full_name);
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Could not save your name.');
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="flex-1 block">
        <span className="text-xs font-mono uppercase tracking-widest text-slate-400">
          Full name, exactly as it should appear on the certificate
        </span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
          placeholder="e.g. Amira Haddad"
          required
          minLength={2}
          maxLength={120}
        />
      </label>
      <button type="submit" className="btn-primary text-sm py-2.5 px-4" disabled={busy}>
        {busy ? 'Saving…' : 'Save name'}
      </button>
      {error && <p className="text-sm text-red-300 sm:basis-full">{error}</p>}
    </form>
  );
};

const SlotsForm = ({
  code,
  onDone,
}: {
  code: string;
  onDone: (adv: CertificationStatus['advanced']) => void;
}) => {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const [slots, setSlots] = useState(['', '', '']);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const minLocal = new Date(Date.now() + 24 * 3600 * 1000).toISOString().slice(0, 16);
  return (
    <form
      className="mt-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const isos = slots
          .filter((s) => s)
          .map((s) => new Date(s).toISOString());
        if (isos.length === 0) {
          setError('Propose at least one window.');
          return;
        }
        setBusy(true);
        setError('');
        try {
          onDone(await academy.proposeSlots(code, isos, tz, note));
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Could not send your windows.');
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="text-sm text-slate-300">
        Propose up to three 60-minute windows that suit you (your clock: {tz}). Your examiner
        confirms one and you receive the meeting link by email.
      </p>
      <div className="grid sm:grid-cols-3 gap-3 mt-3">
        {slots.map((s, i) => (
          <label key={i} className="block">
            <span className="text-xs font-mono uppercase tracking-widest text-slate-400">
              Window {i + 1}
            </span>
            <input
              type="datetime-local"
              value={s}
              min={minLocal}
              onChange={(e) => setSlots(slots.map((v, j) => (j === i ? e.target.value : v)))}
              className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
              required={i === 0}
            />
          </label>
        ))}
      </div>
      <label className="block mt-3">
        <span className="text-xs font-mono uppercase tracking-widest text-slate-400">
          Note for your examiner (optional)
        </span>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
          placeholder="e.g. Mornings in my time zone are best"
        />
      </label>
      {error && <p className="text-sm text-red-300 mt-2">{error}</p>}
      <button type="submit" className="btn-primary text-sm py-2.5 px-4 mt-4" disabled={busy}>
        <CalendarClock className="w-4 h-4" aria-hidden="true" />
        {busy ? 'Sending…' : 'Send my windows'}
      </button>
    </form>
  );
};

/* "Request a fee waiver" — the candidate asks; only the instructor decides,
 * in the admin panel. Sending it opens nothing and charges nothing. */
const WaiverForm = ({
  code,
  reasons,
  price,
  onDone,
  onCancel,
}: {
  code: string;
  reasons: { key: string; label: string }[];
  price: string;
  onDone: (adv: CertificationStatus['advanced']) => void;
  onCancel: () => void;
}) => {
  const [reason, setReason] = useState(reasons[0]?.key ?? 'employer');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const needsNote = reason === 'other';
  return (
    <form
      className="mt-4 rounded-lg border border-slate-700/70 bg-slate-950/40 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (needsNote && !note.trim()) {
          setError('Tell the instructor a little about your situation.');
          return;
        }
        setBusy(true);
        setError('');
        try {
          onDone(await academy.requestFeeWaiver(code, reason, note.trim()));
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Could not send your request.');
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="text-sm text-slate-300">
        Ask the instructor to waive the {price} fee. Every request is reviewed personally and
        answered by email. Nothing is charged, and you can still register and pay while you wait.
      </p>
      <fieldset className="mt-3 space-y-2">
        <legend className="text-xs font-mono uppercase tracking-widest text-slate-400">
          Why are you asking?
        </legend>
        {reasons.map((r) => (
          <label key={r.key} className="flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
            <input
              type="radio"
              name="waiver-reason"
              value={r.key}
              checked={reason === r.key}
              onChange={() => setReason(r.key)}
              className="accent-cyan-400"
            />
            {r.label}
          </label>
        ))}
      </fieldset>
      <label className="block mt-3">
        <span className="text-xs font-mono uppercase tracking-widest text-slate-400">
          {needsNote ? 'Your note to the instructor' : 'Note for the instructor (optional)'}
        </span>
        <textarea
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          required={needsNote}
          className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
          placeholder="e.g. My employer, Acme Turbines, sponsors my training and pays for certifications."
        />
      </label>
      {error && <p className="text-sm text-red-300 mt-2">{error}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="submit" className="btn-primary text-sm py-2 px-4" disabled={busy}>
          <MailQuestion className="w-4 h-4" aria-hidden="true" />
          {busy ? 'Sending…' : 'Send my request'}
        </button>
        <button type="button" className="btn-ghost text-sm" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
};

/* "Pay before the interview": the instructor let the candidate start unpaid.
 * The written examination is open; the interview waits for this payment. */
const FeeDue = ({
  code,
  amount,
  confirming,
}: {
  code: string;
  amount: string;
  confirming: boolean;
}) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
      <p className="text-sm text-amber-100">
        <span className="font-semibold">Examination fee: {amount}</span>, due before you book your
        oral examination. You can pay it now or after the written examination.
      </p>
      {confirming ? (
        <p className="mt-2 text-sm text-cyan-300 animate-pulse">Confirming your payment…</p>
      ) : (
        <button
          type="button"
          className="btn-primary text-sm py-2 px-4 mt-3"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError('');
            try {
              const { url } = await academy.payExamFee(code);
              window.location.href = url;
            } catch (err) {
              setError(err instanceof ApiError ? err.message : 'Could not start checkout.');
              setBusy(false);
            }
          }}
        >
          <CreditCard className="w-4 h-4" aria-hidden="true" />
          {busy ? 'Opening checkout…' : `Pay ${amount}`}
        </button>
      )}
      {error && <p className="text-sm text-red-300 mt-2">{error}</p>}
    </div>
  );
};

/* The per-competency result of the written examination. The candidate sees it
 * once the journey has an outcome; the instructor sees the same breakdown in
 * the admin panel before the oral examination. */
const CompetencyBreakdown = ({ rows }: { rows: CompetencyScore[] }) => (
  <div className="mt-4">
    <div className="text-xs uppercase tracking-wider text-slate-400">
      Your written examination, competency by competency
    </div>
    <ul className="mt-2 space-y-2">
      {rows.map((r) => (
        <li key={r.id}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm text-slate-200">{r.label}</span>
            <span className="text-xs font-mono text-slate-300 shrink-0">
              {r.correct}/{r.total} · {r.pct}%
            </span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-slate-700/60 overflow-hidden">
            <div
              className={`h-full rounded-full ${r.pct >= 80 ? 'bg-emerald-400' : r.pct >= 60 ? 'bg-amber-400' : 'bg-rose-400'}`}
              style={{ width: `${Math.max(2, Math.min(100, r.pct))}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  </div>
);

const Step = ({
  n,
  title,
  children,
  active,
}: {
  n: number;
  title: string;
  children?: React.ReactNode;
  active?: boolean;
}) => (
  <div className={`flex gap-3 ${active ? '' : 'opacity-60'}`}>
    <div className="w-7 h-7 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 font-mono text-xs flex items-center justify-center shrink-0">
      {n}
    </div>
    <div>
      <div className="text-sm font-semibold text-white">{title}</div>
      {children && <div className="text-sm text-slate-300 mt-0.5">{children}</div>}
    </div>
  </div>
);

const CertificationPanel: React.FC<{
  code: string;
  paidReturn?: boolean;
  /* ?advanced=start — the "Book my examination" button in the completion
   * certificate email. Bring the examined-tier card into view and mark it,
   * so the Register button is the first thing on screen. Nothing is
   * purchased or submitted by the page load itself; checkout still needs
   * the click (a mail scanner opening this link must not create an order). */
  startAdvanced?: boolean;
}> = ({ code, paidReturn, startAdvanced }) => {
  const [data, setData] = useState<CertificationStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const verifiedRef = useRef<HTMLElement | null>(null);
  const [spotlight, setSpotlight] = useState(false);
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await academy.certification(code));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load certification status.');
    }
  }, [code]);

  useEffect(() => {
    void load();
  }, [load]);

  // Back from Stripe: the webhook may land a few seconds after the redirect.
  // `confirming` covers the polling window only, so a deferred fee whose
  // confirmation is slow shows its Pay button again rather than a spinner
  // that never ends.
  const [confirming, setConfirming] = useState(!!paidReturn);
  useEffect(() => {
    if (!paidReturn) return;
    let tries = 0;
    const t = window.setInterval(async () => {
      tries += 1;
      await load();
      if (tries >= 10) {
        window.clearInterval(t);
        setConfirming(false);
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [paidReturn, load]);

  // Deep link from the email: once the card exists, scroll to it and hold a
  // highlight ring on it for a few seconds.
  useEffect(() => {
    if (!startAdvanced || !data) return;
    const el = verifiedRef.current;
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setSpotlight(true);
    const t = window.setTimeout(() => setSpotlight(false), 6000);
    return () => window.clearTimeout(t);
  }, [startAdvanced, data]);

  if (error) {
    return (
      <div className="card p-6 mb-8">
        <p className="text-sm text-slate-300">{error}</p>
      </div>
    );
  }
  if (!data) return null;

  const { completion, advanced } = data;
  const state = advanced.state;
  const price = money(advanced.price_cents, advanced.currency);
  const feeDue = state?.fee_status === 'due';
  const reasonLabel = (key: string) =>
    advanced.waiver?.reasons.find((r) => r.key === key)?.label ?? '';

  // The one way to register with payment: before any request, while a
  // request waits, and after the instructor asked for payment.
  const registerButton = advanced.can_purchase ? (
    <button
      type="button"
      className="btn-primary"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const { url } = await academy.advancedCheckout(code);
          window.location.href = url;
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Could not start checkout.');
          setBusy(false);
        }
      }}
    >
      <ShieldCheck className="w-4 h-4" aria-hidden="true" />
      {busy ? 'Opening checkout…' : `Register for the examination, ${price}`}
    </button>
  ) : (
    <p className="text-sm text-amber-200">{advanced.purchase_blocked_reason}</p>
  );

  return (
    <>
      {/* ---- Certificate of Attendance (issued by a moderator for live-cohort
             attendees; shown only when held — there is no learner action) ---- */}
      {data.attendance?.certificate && (
        <section className="card p-6 mb-8" aria-labelledby="cert-attendance">
          <div className="flex items-start gap-4">
            <BadgeCheck className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h2 id="cert-attendance" className="font-semibold text-white">
                  Certificate of Attendance
                </h2>
                <span className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border border-slate-600 text-slate-300">
                  Live cohort
                </span>
              </div>
              <p className="text-sm text-slate-300 mt-1">
                Issued for attending the live, instructor-led course. Complete the online
                course below for your Certificate of Completion, which is stronger — it
                records that you were assessed, not only present.
              </p>
              <div className="mt-4">
                <CertificateCard cert={data.attendance.certificate} />
              </div>
            </div>
          </div>
        </section>
      )}

      {/* ---- Tier 1: Certificate of Completion ---- */}
      <section className="card p-6 mb-8" aria-labelledby="cert-completion">
        <div className="flex items-start gap-4">
          <Award className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h2 id="cert-completion" className="font-semibold text-white">
                Certificate of Completion
              </h2>
              <span className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border border-slate-600 text-slate-300">
                Included
              </span>
            </div>

            {completion.certificate ? (
              <div className="mt-4">
                <CertificateCard cert={completion.certificate} />
              </div>
            ) : completion.awaiting_name ? (
              <>
                <p className="text-sm text-slate-300 mt-1">
                  You have completed everything. Add the name to print on your certificate and
                  it will be issued immediately and emailed to you.
                </p>
                <NameForm initial={data.full_name} onSaved={() => void load()} />
              </>
            ) : (
              <>
                <p className="text-sm text-slate-300 mt-1">
                  Issued automatically the moment every lesson is complete and every module
                  evaluation and mastery check is passed. It carries a public verification
                  code and can be added to your LinkedIn profile in one click.
                </p>
                <div className="grid sm:grid-cols-2 gap-3 mt-4 text-sm">
                  <div className="rounded-lg border border-slate-700/70 bg-slate-950/40 px-4 py-3">
                    <div className="text-xs font-mono uppercase tracking-widest text-slate-400">
                      Lessons
                    </div>
                    <div className="text-white font-semibold tabular-nums mt-0.5">
                      {completion.lessons_done} of {completion.lessons_total}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-700/70 bg-slate-950/40 px-4 py-3">
                    <div className="text-xs font-mono uppercase tracking-widest text-slate-400">
                      Evaluations &amp; mastery checks passed
                    </div>
                    <div className="text-white font-semibold tabular-nums mt-0.5">
                      {completion.sets_passed} of {completion.sets_total}
                    </div>
                  </div>
                </div>
                {!data.full_name && (
                  <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
                    <p className="text-sm text-amber-200">
                      No name on file yet. Add it now so the certificate can be issued the
                      instant you finish.
                    </p>
                    <NameForm initial="" onSaved={() => void load()} />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </section>

      {/* ---- Tier 2: Certificate of Verified Competency ---- */}
      {(advanced.offered || advanced.certificate) && (
        <section
          ref={verifiedRef}
          id="cert-verified-card"
          className={`card p-6 mb-8 border-cyan-500/30 scroll-mt-28 transition-shadow duration-700 ${
            spotlight ? 'ring-2 ring-cyan-400/70 shadow-glow-cyan' : ''
          }`}
          aria-labelledby="cert-verified"
        >
          <div className="flex items-start gap-4">
            <BadgeCheck className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h2 id="cert-verified" className="font-semibold text-white">
                  Certificate of Verified Competency
                </h2>
                <span className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300">
                  Instructor examined · {money(advanced.price_cents, advanced.currency)}
                </span>
              </div>

              {advanced.certificate ? (
                <div className="mt-4">
                  <CertificateCard cert={advanced.certificate} />
                </div>
              ) : (
                <>
                  {paidReturn && !state && (
                    <p className="mt-2 text-sm text-cyan-300 animate-pulse">
                      Confirming your payment…
                    </p>
                  )}
                  {!state && (
                    <>
                      <p className="text-sm text-slate-300 mt-1">
                        The credential a hiring manager can trust: after an advanced written
                        examination, you are examined live, one-on-one by video, for{' '}
                        {advanced.interview_minutes} minutes by the instructor. A pass issues a
                        certificate signed by the instructor attesting that you were examined in
                        person and demonstrated a verified command of{' '}
                        <span className="text-white">every key principle</span> of the subject.
                      </p>
                      <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3 mt-4">
                        <Step n={1} title="Written examination" active>
                          {advanced.exam_item_count} analysis-level questions, pass mark{' '}
                          {advanced.exam_threshold}%, {advanced.exam_max_attempts} attempts.
                        </Step>
                        <Step n={2} title="Propose your interview windows" active>
                          Three 60-minute windows in your own time zone.
                        </Step>
                        <Step n={3} title="Live oral examination" active>
                          One-on-one by video conference. Camera on, photo ID at the start.
                        </Step>
                        <Step n={4} title="Signed certificate" active>
                          Issued only by the instructor after the examination. Digitally
                          signed, publicly verifiable, LinkedIn-ready.
                        </Step>
                      </div>
                      <button
                        type="button"
                        className="btn-ghost mt-4"
                        onClick={() => setShowAll(!showAll)}
                      >
                        {showAll ? 'Hide' : 'See'} the principles examined
                      </button>
                      {showAll && (
                        <ol className="mt-2 grid sm:grid-cols-2 gap-x-6 gap-y-1 text-sm text-slate-300 list-decimal list-inside">
                          {advanced.competencies.map((c) => (
                            <li key={c}>{c}</li>
                          ))}
                        </ol>
                      )}
                      {advanced.waiver?.declined && (
                        <div className="mt-5 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
                          <p className="text-sm text-amber-100">
                            The instructor could not waive the fee. Register below to take the
                            examination.
                          </p>
                          {advanced.waiver.message && (
                            <p className="text-sm text-slate-300 mt-1">
                              From the instructor: <em>{advanced.waiver.message}</em>
                            </p>
                          )}
                        </div>
                      )}
                      <div className="mt-5 flex flex-wrap items-center gap-3">
                        {registerButton}
                        {advanced.waiver?.can_request && !asking && (
                          <button
                            type="button"
                            className="text-sm text-cyan-400 hover:text-cyan-300 underline-offset-2 hover:underline"
                            onClick={() => setAsking(true)}
                          >
                            Request a fee waiver
                          </button>
                        )}
                      </div>
                      {asking && advanced.waiver?.can_request && (
                        <WaiverForm
                          code={code}
                          reasons={advanced.waiver.reasons}
                          price={price}
                          onCancel={() => setAsking(false)}
                          onDone={(adv) => {
                            setAsking(false);
                            setData({ ...data, advanced: { ...advanced, ...adv } });
                          }}
                        />
                      )}
                      <p className="text-xs text-slate-500 mt-3">
                        The fee pays for the examination, not the outcome. If mastery is not
                        demonstrated at the first session, one complimentary re-examination is
                        offered after a study period; there is no refund for an unsuccessful
                        examination.
                      </p>
                    </>
                  )}

                  {state && state.status === 'waiver_requested' && (
                    <div className="mt-3">
                      <div className="flex gap-3">
                        <MailQuestion className="w-5 h-5 text-cyan-300 shrink-0 mt-0.5" aria-hidden="true" />
                        <div>
                          <div className="text-sm font-semibold text-white">
                            Your fee-waiver request is with the instructor
                          </div>
                          <p className="text-sm text-slate-300 mt-0.5">
                            Sent {fmtDate(state.waiver_requested_at)}
                            {reasonLabel(state.waiver_reason) && (
                              <> · {reasonLabel(state.waiver_reason)}</>
                            )}
                            . You will hear back by email, and nothing has been charged.
                          </p>
                        </div>
                      </div>
                      <p className="text-sm text-slate-400 mt-4">
                        Prefer not to wait? Registering and paying now closes the request.
                      </p>
                      <div className="mt-3">{registerButton}</div>
                    </div>
                  )}

                  {state && state.status === 'purchased' && (
                    <div className="mt-3">
                      <Step n={1} title="Written examination" active>
                        {advanced.exam_item_count} questions · pass mark {advanced.exam_threshold}% ·
                        attempt {Math.min(state.exam_attempts + 1, advanced.exam_max_attempts)} of{' '}
                        {advanced.exam_max_attempts}
                        {state.exam_attempts > 0 && (
                          <> · best so far {state.exam_best_pct}%</>
                        )}
                      </Step>
                      <Link to={`/learn/advanced-exam/${code}`} className="btn-primary mt-4">
                        <ClipboardCheck className="w-4 h-4" aria-hidden="true" />
                        {state.exam_attempts > 0 ? 'Retake the written examination' : 'Start the written examination'}
                      </Link>
                      {state.fee_status === 'waived' && (
                        <p className="text-xs text-slate-400 mt-3">
                          No fee to pay: the instructor waived it.
                        </p>
                      )}
                      {feeDue && (
                        <FeeDue
                          code={code}
                          amount={money(state.fee_due_cents, advanced.currency)}
                          confirming={confirming}
                        />
                      )}
                    </div>
                  )}

                  {state && state.status === 'exam_failed' && (
                    <p className="mt-3 text-sm text-amber-200">
                      Both attempts at the written examination are used (best {state.exam_best_pct}%).
                      Write to info@proreadyengineer.com to discuss a further attempt.
                    </p>
                  )}

                  {state &&
                    (state.status === 'exam_passed' ||
                      state.status === 'slots_proposed' ||
                      state.status === 'retake_pending') && (
                      <div className="mt-3">
                        <Step n={2} title={state.interview_no > 1 ? 'Propose windows for your re-examination' : 'Propose your interview windows'} active>
                          {state.status === 'retake_pending' && state.retake_after && (
                            <>Your complimentary re-examination can be proposed on or after {fmtDate(state.retake_after)}. </>
                          )}
                          {state.status === 'slots_proposed' && (
                            <>Sent. Waiting for your examiner to confirm one of your windows. You will receive the meeting link by email.</>
                          )}
                        </Step>
                        {state.status === 'slots_proposed' && (
                          <ul className="mt-3 text-sm text-slate-300 space-y-1">
                            {state.proposed_slots.map((iso) => (
                              <li key={iso} className="font-mono text-xs text-slate-300">
                                {new Date(iso).toLocaleString(undefined, {
                                  dateStyle: 'full',
                                  timeStyle: 'short',
                                })}
                              </li>
                            ))}
                          </ul>
                        )}
                        {state.status === 'slots_proposed' && (
                          <p className="mt-3 text-xs text-slate-500">
                            Need different times? Send a new set below and it replaces the old one.
                          </p>
                        )}
                        {state.can_propose ? (
                          <SlotsForm
                            code={code}
                            onDone={(adv) => setData({ ...data, advanced: { ...advanced, ...adv } })}
                          />
                        ) : feeDue ? (
                          // "Pay before the interview": the payment is the next step.
                          <FeeDue
                            code={code}
                            amount={money(state.fee_due_cents, advanced.currency)}
                            confirming={confirming}
                          />
                        ) : (
                          <p className="mt-2 text-sm text-amber-200">{state.propose_blocked_reason}</p>
                        )}
                      </div>
                    )}

                  {state && state.status === 'scheduled' && (
                    <div className="mt-3">
                      <Step n={3} title={state.interview_no > 1 ? 'Your re-examination is booked' : 'Your oral examination is booked'} active>
                        <ul className="mt-1 space-y-0.5">
                          {state.scheduled_lines.map((l) => (
                            <li key={l}>{l}</li>
                          ))}
                        </ul>
                        <p className="mt-2">
                          {advanced.interview_minutes} minutes, one-on-one by video. Join from a quiet
                          place with your camera on and have a photo ID ready. Questions are asked
                          without notice. Think aloud; the reasoning is what is examined.
                        </p>
                      </Step>
                      {state.meeting_url && (
                        <a
                          href={state.meeting_url}
                          className="btn-primary mt-4"
                          target="_blank"
                          rel="noopener"
                        >
                          <Video className="w-4 h-4" aria-hidden="true" /> Join the examination
                        </a>
                      )}
                    </div>
                  )}

                  {state && state.status === 'failed' && (
                    <p className="mt-3 text-sm text-slate-300">
                      Your examiner concluded that mastery was not demonstrated at the re-examination,
                      so no Certificate of Verified Competency was issued. Your Certificate of Completion
                      and course access are unaffected.
                    </p>
                  )}
                  {state && state.status === 'cancelled' && (
                    <p className="mt-3 text-sm text-slate-300">This examination was cancelled.</p>
                  )}
                  {state && state.exam_breakdown.length > 0 && (
                    <CompetencyBreakdown rows={state.exam_breakdown} />
                  )}
                </>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  );
};

export default CertificationPanel;
