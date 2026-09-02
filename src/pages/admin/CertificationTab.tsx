import React, { useCallback, useEffect, useState } from 'react';
import {
  Award,
  BadgeCheck,
  CalendarClock,
  ExternalLink,
  FileSignature,
  RefreshCw,
  Settings2,
  Users,
} from 'lucide-react';
import { api, API_BASE, reportError, type Course } from './lib';
import { EmptyState, Kpi, Notice } from './ui';

/* Certification tab — the one place the instructor-examined tier is decided.
 *
 * Everything here is an explicit admin action: confirming an interview
 * time, recording the outcome (the ONLY path to a verified certificate),
 * giving a written exam back, comping a candidate, revoking or re-issuing a
 * certificate. Nothing on this tab happens automatically. */

type Candidate = {
  id: number;
  email: string;
  full_name: string;
  status: string;
  source: string;
  amount_cents: number;
  currency: string;
  exam_attempts: number;
  exam_best_pct: number;
  proposed_slots: { iso: string; lines: string[] }[];
  learner_timezone: string;
  learner_note: string;
  scheduled_at: string | null;
  scheduled_lines: string[];
  meeting_url: string;
  interview_no: number;
  retake_after: string | null;
  outcome_note: string;
  certificate_code: string;
  created_at: string;
};

type CertRow = {
  code: string;
  tier: 'completion' | 'verified';
  status: 'issued' | 'revoked';
  revoke_reason: string;
  email: string;
  learner_name: string;
  issued_at: string;
  exam_date: string | null;
  signature_valid: boolean;
  email_sent_at: string | null;
  verify_url: string;
  pdf_url: string;
};

type Overview = {
  product: {
    code: string;
    title: string;
    advanced_cert_enabled: boolean;
    advanced_cert_price_cents: number;
    currency: string;
    certificate_descriptor: string;
    certificate_descriptor_effective: string;
    certificate_competencies: string[];
    certificate_competencies_effective: string[];
  };
  exam_item_count: number;
  signature_uploaded: boolean;
  signing_key_id: string;
  signing_key_from_env: boolean;
  interview_minutes: number;
  candidates: Candidate[];
  certificates: CertRow[];
  counts: { completion: number; verified: number; awaiting_action: number };
};

const STATUS_LABEL: Record<string, string> = {
  purchased: 'Written exam open',
  exam_passed: 'Awaiting learner windows',
  slots_proposed: 'Windows proposed — confirm one',
  scheduled: 'Interview booked',
  retake_pending: 'Re-examination pending',
  passed: 'Passed — certificate issued',
  failed: 'Did not pass',
  exam_failed: 'Written exam attempts used',
  cancelled: 'Cancelled',
};

const badgeCls = (status: string) =>
  status === 'passed'
    ? 'border-emerald-700 text-emerald-200 bg-emerald-950/40'
    : status === 'slots_proposed' || status === 'scheduled'
      ? 'border-amber-700 text-amber-200 bg-amber-950/40'
      : status === 'failed' || status === 'cancelled' || status === 'exam_failed'
        ? 'border-red-900 text-red-300 bg-red-950/30'
        : 'border-slate-600 text-slate-200 bg-slate-800/60';

const fmt = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] || '');
    r.onerror = () => reject(new Error('Could not read the file.'));
    r.readAsDataURL(file);
  });
}

export default function CertificationTab({
  course,
  onAuthError,
  gotoSettings,
}: {
  course: Course;
  onAuthError: () => void;
  gotoSettings: () => void;
}) {
  const productCode = course.recorded_product_code;
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const note = (m: string) => {
    setFlash(m);
    window.setTimeout(() => setFlash(null), 5000);
  };

  const load = useCallback(async () => {
    if (!productCode) return;
    try {
      setData(await api<Overview>(`/api/admin/academy/certification/${encodeURIComponent(productCode)}`));
    } catch (e) {
      reportError(e, onAuthError, setError);
    }
  }, [productCode, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(key: string, fn: () => Promise<unknown>, done: string) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      note(done);
      await load();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  }

  if (!productCode) {
    return (
      <EmptyState
        icon={<Award className="w-5 h-5" />}
        title="No course product linked"
        hint="Link this cohort to its course product in Settings and this tab becomes the certification desk: examined-tier candidates, interview scheduling, outcomes and issued certificates."
        action={
          <button onClick={gotoSettings} className="btn-secondary text-sm py-2 px-4">
            Open Settings to link one
          </button>
        }
      />
    );
  }
  if (!data) return <p className="text-sm text-slate-400">Loading…</p>;

  return (
    <div className="space-y-8">
      {error && <Notice kind="error">{error}</Notice>}
      {flash && <Notice kind="success">{flash}</Notice>}

      <div className="grid sm:grid-cols-3 gap-4">
        <Kpi label="Completion certificates" value={String(data.counts.completion)} accent="cyan" />
        <Kpi label="Verified competency certificates" value={String(data.counts.verified)} accent="emerald" />
        <Kpi
          label="Waiting on you"
          value={String(data.counts.awaiting_action)}
          accent={data.counts.awaiting_action ? 'amber' : 'slate'}
        />
      </div>

      <SettingsCard data={data} busy={busy} run={run} />

      <section>
        <h3 className="text-base font-semibold text-white flex items-center gap-2 mb-3">
          <Users className="w-4 h-4 text-cyan-400" /> Examined-tier candidates
          <button type="button" onClick={() => void load()} className="ml-auto btn-ghost text-xs" title="Refresh">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </h3>
        <CompForm productCode={productCode} busy={busy} run={run} />
        {data.candidates.length === 0 ? (
          <p className="text-sm text-slate-400 mt-3">No candidates yet.</p>
        ) : (
          <div className="space-y-4 mt-4">
            {data.candidates.map((c) => (
              <CandidateCard key={c.id} c={c} minutes={data.interview_minutes} busy={busy} run={run} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="text-base font-semibold text-white flex items-center gap-2 mb-3">
          <BadgeCheck className="w-4 h-4 text-cyan-400" /> Issued certificates
        </h3>
        {data.certificates.length === 0 ? (
          <p className="text-sm text-slate-400">Nothing issued yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-900/70 text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="text-left px-3 py-2">Credential</th>
                  <th className="text-left px-3 py-2">Holder</th>
                  <th className="text-left px-3 py-2">Issued</th>
                  <th className="text-left px-3 py-2">Status</th>
                  <th className="text-left px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.certificates.map((r) => (
                  <CertificateRow key={r.code} r={r} busy={busy} run={run} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// ----- Settings ---------------------------------------------------------------

function SettingsCard({
  data,
  busy,
  run,
}: {
  data: Overview;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, done: string) => Promise<void>;
}) {
  const p = data.product;
  const [enabled, setEnabled] = useState(p.advanced_cert_enabled);
  const [price, setPrice] = useState(String(p.advanced_cert_price_cents / 100));
  const [descriptor, setDescriptor] = useState(p.certificate_descriptor);
  const [competencies, setCompetencies] = useState(p.certificate_competencies.join('\n'));
  const [sigFile, setSigFile] = useState<File | null>(null);

  useEffect(() => {
    setEnabled(p.advanced_cert_enabled);
    setPrice(String(p.advanced_cert_price_cents / 100));
    setDescriptor(p.certificate_descriptor);
    setCompetencies(p.certificate_competencies.join('\n'));
  }, [p]);

  return (
    <section className="card p-5">
      <h3 className="text-base font-semibold text-white flex items-center gap-2 mb-4">
        <Settings2 className="w-4 h-4 text-cyan-400" /> Certification settings
      </h3>
      <div className="grid md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <label className="flex items-center gap-3 text-sm text-slate-200">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="accent-cyan-400" />
            Offer the instructor-examined certificate on this course
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-300">Examined-tier price (USD)</span>
            <input
              type="number"
              min={0}
              step={1}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className="mt-1 w-40 rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white"
            />
          </label>
          <div className="text-xs text-slate-400 space-y-1">
            <div>
              Written exam bank: <span className="text-slate-200">{data.exam_item_count} items</span>
              {data.exam_item_count === 0 && <span className="text-amber-300"> — the tier cannot be offered without one</span>}
            </div>
            <div>
              Instructor signature:{' '}
              {data.signature_uploaded ? (
                <span className="text-emerald-300">uploaded</span>
              ) : (
                <span className="text-amber-300">missing — verified certificates will refuse to issue</span>
              )}
            </div>
            <div>
              Signing key: <span className="font-mono text-slate-200">{data.signing_key_id}</span>{' '}
              {data.signing_key_from_env ? (
                <span className="text-emerald-300">(CERT_SIGNING_KEY set)</span>
              ) : (
                <span className="text-amber-300">(derived — set CERT_SIGNING_KEY on Render)</span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="file"
              accept="image/png"
              onChange={(e) => setSigFile(e.target.files?.[0] ?? null)}
              className="text-xs text-slate-300"
            />
            <button
              type="button"
              disabled={!sigFile || busy === 'sig'}
              className="btn-secondary text-xs py-1.5 px-3"
              onClick={() =>
                sigFile &&
                run(
                  'sig',
                  async () =>
                    api('/api/admin/academy/certification/signature', {
                      method: 'POST',
                      body: JSON.stringify({ png_b64: await fileToBase64(sigFile) }),
                    }),
                  'Signature uploaded.'
                )
              }
            >
              <FileSignature className="w-3.5 h-3.5" /> Upload signature PNG
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {(['completion', 'verified'] as const).map((tier) => (
              <a
                key={tier}
                href={`${API_BASE}/api/admin/academy/certification/${encodeURIComponent(p.code)}/sample.pdf?tier=${tier}`}
                target="_blank"
                rel="noopener"
                className="btn-ghost text-xs"
              >
                <ExternalLink className="w-3.5 h-3.5" /> Preview {tier === 'completion' ? 'Completion' : 'Verified Competency'} specimen
              </a>
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-300">Programme descriptor (printed on both certificates)</span>
            <textarea
              rows={4}
              value={descriptor}
              onChange={(e) => setDescriptor(e.target.value)}
              placeholder={p.certificate_descriptor_effective}
              className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white text-sm"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-300">Principles examined — one per line (verified certificate)</span>
            <textarea
              rows={7}
              value={competencies}
              onChange={(e) => setCompetencies(e.target.value)}
              placeholder={p.certificate_competencies_effective.join('\n')}
              className="mt-1 w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white text-sm"
            />
          </label>
        </div>
      </div>
      <div className="mt-4">
        <button
          type="button"
          disabled={busy === 'settings'}
          className="btn-primary text-sm py-2 px-4"
          onClick={() =>
            run(
              'settings',
              () =>
                api(`/api/admin/academy/products/${encodeURIComponent(p.code)}`, {
                  method: 'PATCH',
                  body: JSON.stringify({
                    advanced_cert_enabled: enabled,
                    advanced_cert_price_cents: Math.round(Number(price || 0) * 100),
                    certificate_descriptor: descriptor,
                    certificate_competencies: competencies.split('\n').map((s) => s.trim()).filter(Boolean),
                  }),
                }),
              'Certification settings saved.'
            )
          }
        >
          Save settings
        </button>
      </div>
    </section>
  );
}

// ----- Comp form ----------------------------------------------------------------

function CompForm({
  productCode,
  busy,
  run,
}: {
  productCode: string;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, done: string) => Promise<void>;
}) {
  const [email, setEmail] = useState('');
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!email) return;
        void run(
          'comp',
          () =>
            api('/api/admin/academy/certification/comp', {
              method: 'POST',
              body: JSON.stringify({ email, product_code: productCode, send_email: true }),
            }),
          `Examination opened for ${email} (no charge).`
        ).then(() => setEmail(''));
      }}
    >
      <label className="block">
        <span className="text-[11px] uppercase tracking-wider text-slate-300">Open the examined tier without payment</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="learner@example.com"
          className="mt-1 w-72 rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white text-sm"
        />
      </label>
      <button type="submit" disabled={busy === 'comp' || !email} className="btn-secondary text-sm py-2 px-4">
        Comp candidate
      </button>
    </form>
  );
}

// ----- Candidate card ------------------------------------------------------------

function CandidateCard({
  c,
  minutes,
  busy,
  run,
}: {
  c: Candidate;
  minutes: number;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, done: string) => Promise<void>;
}) {
  const [pick, setPick] = useState<string>(c.proposed_slots[0]?.iso ?? '');
  const [custom, setCustom] = useState('');
  const [meeting, setMeeting] = useState(c.meeting_url);
  const [outcomeNote, setOutcomeNote] = useState('');
  const [retakeAfter, setRetakeAfter] = useState('');
  const [cancelNote, setCancelNote] = useState('');
  const key = `cand-${c.id}`;
  const canSchedule = ['slots_proposed', 'exam_passed', 'retake_pending', 'scheduled'].includes(c.status);

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-white font-semibold">{c.full_name || c.email}</div>
          <div className="text-xs text-slate-400">
            {c.email} · {c.source === 'manual' ? 'comped' : `${c.source} · $${(c.amount_cents / 100).toFixed(0)}`} ·
            opened {fmt(c.created_at)}
          </div>
        </div>
        <span className={`text-xs px-2 py-1 rounded-full border ${badgeCls(c.status)}`}>
          {STATUS_LABEL[c.status] ?? c.status}
          {c.interview_no > 1 && c.status !== 'passed' ? ' · re-exam' : ''}
        </span>
      </div>

      <div className="grid md:grid-cols-2 gap-4 mt-4 text-sm">
        <div className="space-y-1 text-slate-300">
          <div>
            Written exam: {c.exam_attempts} attempt{c.exam_attempts === 1 ? '' : 's'}
            {c.exam_attempts > 0 && <> · best {c.exam_best_pct}%</>}
          </div>
          {c.proposed_slots.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-400 mt-2">Proposed windows{c.learner_timezone ? ` (${c.learner_timezone})` : ''}</div>
              <ul className="mt-1 space-y-1">
                {c.proposed_slots.map((s) => (
                  <li key={s.iso} className="flex items-start gap-2">
                    {canSchedule && c.status !== 'scheduled' && (
                      <input
                        type="radio"
                        name={`pick-${c.id}`}
                        checked={pick === s.iso}
                        onChange={() => setPick(s.iso)}
                        className="mt-1 accent-cyan-400"
                      />
                    )}
                    <span className="text-xs">{s.lines.join(' · ')}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {c.learner_note && <div className="text-xs text-slate-400 mt-2">Note: {c.learner_note}</div>}
          {c.scheduled_lines.length > 0 && (
            <div className="mt-2">
              <div className="text-xs uppercase tracking-wider text-slate-400">Booked</div>
              {c.scheduled_lines.map((l) => (
                <div key={l} className="text-xs">{l}</div>
              ))}
              {c.meeting_url && (
                <a href={c.meeting_url} target="_blank" rel="noopener" className="text-xs text-cyan-400 break-all">
                  {c.meeting_url}
                </a>
              )}
            </div>
          )}
          {c.retake_after && c.status === 'retake_pending' && (
            <div className="text-xs text-slate-400">Re-examination can be proposed from {c.retake_after}</div>
          )}
          {c.outcome_note && <div className="text-xs text-slate-400 mt-2">Your note: {c.outcome_note}</div>}
          {c.certificate_code && (
            <div className="text-xs mt-2">
              Certificate <span className="font-mono text-slate-200">{c.certificate_code}</span>
            </div>
          )}
        </div>

        <div className="space-y-3">
          {canSchedule && c.status !== 'scheduled' && (
            <div className="rounded-lg border border-slate-800 p-3 space-y-2">
              <div className="text-xs uppercase tracking-wider text-slate-400 flex items-center gap-1">
                <CalendarClock className="w-3.5 h-3.5" /> Confirm a time ({minutes} min)
              </div>
              <input
                type="datetime-local"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                className="w-full rounded-lg bg-slate-950/70 border border-slate-700 px-2 py-1.5 text-white text-xs"
                title="Or pick a different time (your local clock)"
              />
              <input
                type="url"
                value={meeting}
                onChange={(e) => setMeeting(e.target.value)}
                placeholder="Meeting link (Zoom / Meet / Teams)"
                className="w-full rounded-lg bg-slate-950/70 border border-slate-700 px-2 py-1.5 text-white text-xs"
              />
              <button
                type="button"
                disabled={busy === key || (!pick && !custom)}
                className="btn-primary text-xs py-1.5 px-3"
                onClick={() =>
                  run(
                    key,
                    () =>
                      api(`/api/admin/academy/certification/advanced/${c.id}/schedule`, {
                        method: 'POST',
                        body: JSON.stringify({
                          at: custom ? new Date(custom).toISOString() : pick,
                          meeting_url: meeting,
                        }),
                      }),
                    'Interview confirmed — the candidate has been emailed the details and a calendar file.'
                  )
                }
              >
                Confirm {custom ? 'custom time' : 'selected window'} &amp; email candidate
              </button>
            </div>
          )}

          {c.status === 'scheduled' && (
            <div className="rounded-lg border border-cyan-500/30 p-3 space-y-2">
              <div className="text-xs uppercase tracking-wider text-slate-400">Record the outcome</div>
              <textarea
                rows={3}
                value={outcomeNote}
                onChange={(e) => setOutcomeNote(e.target.value)}
                placeholder="Private examiner notes (never shown to the learner)"
                className="w-full rounded-lg bg-slate-950/70 border border-slate-700 px-2 py-1.5 text-white text-xs"
              />
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={busy === key}
                  className="btn-primary text-xs py-1.5 px-3"
                  onClick={() =>
                    run(
                      key,
                      () =>
                        api(`/api/admin/academy/certification/advanced/${c.id}/outcome`, {
                          method: 'POST',
                          body: JSON.stringify({ result: 'pass', note: outcomeNote }),
                        }),
                      'Pass recorded — the signed Certificate of Verified Competency has been issued and emailed.'
                    )
                  }
                >
                  Pass — issue signed certificate
                </button>
                {c.interview_no < 2 && (
                  <>
                    <input
                      type="date"
                      value={retakeAfter}
                      onChange={(e) => setRetakeAfter(e.target.value)}
                      className="rounded-lg bg-slate-950/70 border border-slate-700 px-2 py-1.5 text-white text-xs"
                      title="Earliest date for the re-examination (default: 14 days)"
                    />
                    <button
                      type="button"
                      disabled={busy === key}
                      className="btn-secondary text-xs py-1.5 px-3"
                      onClick={() =>
                        run(
                          key,
                          () =>
                            api(`/api/admin/academy/certification/advanced/${c.id}/outcome`, {
                              method: 'POST',
                              body: JSON.stringify({
                                result: 'retake',
                                note: outcomeNote,
                                retake_after: retakeAfter || null,
                              }),
                            }),
                          'Recorded as "not yet" — the candidate has been offered the complimentary re-examination.'
                        )
                      }
                    >
                      Not yet — offer re-examination
                    </button>
                  </>
                )}
                {c.interview_no >= 2 && (
                  <button
                    type="button"
                    disabled={busy === key}
                    className="btn-secondary text-xs py-1.5 px-3 border-red-900 text-red-300"
                    onClick={() =>
                      run(
                        key,
                        () =>
                          api(`/api/admin/academy/certification/advanced/${c.id}/outcome`, {
                            method: 'POST',
                            body: JSON.stringify({ result: 'fail', note: outcomeNote }),
                          }),
                        'Recorded as not passed — the candidate has been informed.'
                      )
                    }
                  >
                    Did not pass
                  </button>
                )}
                <button
                  type="button"
                  disabled={busy === key}
                  className="btn-ghost text-xs"
                  onClick={() =>
                    run(
                      key,
                      () => api(`/api/admin/academy/certification/advanced/${c.id}/reopen`, { method: 'POST' }),
                      'Booking cleared — the candidate can propose new windows.'
                    )
                  }
                >
                  Booking fell through — ask for new windows
                </button>
              </div>
            </div>
          )}

          {c.status === 'exam_failed' && (
            <button
              type="button"
              disabled={busy === key}
              className="btn-secondary text-xs py-1.5 px-3"
              onClick={() =>
                run(
                  key,
                  () => api(`/api/admin/academy/certification/advanced/${c.id}/reset-exam`, { method: 'POST' }),
                  'Written examination attempts reset.'
                )
              }
            >
              Give the written exam back
            </button>
          )}

          {!['passed', 'failed', 'cancelled'].includes(c.status) && (
            <div className="flex items-center gap-2">
              <input
                value={cancelNote}
                onChange={(e) => setCancelNote(e.target.value)}
                placeholder="Reason"
                className="flex-1 rounded-lg bg-slate-950/70 border border-slate-800 px-2 py-1 text-white text-xs"
              />
              <button
                type="button"
                disabled={busy === key || !cancelNote}
                className="btn-ghost text-xs text-red-300"
                onClick={() =>
                  run(
                    key,
                    () =>
                      api(`/api/admin/academy/certification/advanced/${c.id}/cancel`, {
                        method: 'POST',
                        body: JSON.stringify({ note: cancelNote }),
                      }),
                    'Examination cancelled.'
                  )
                }
              >
                Cancel examination
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ----- Certificate row -----------------------------------------------------------

function CertificateRow({
  r,
  busy,
  run,
}: {
  r: CertRow;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, done: string) => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [newName, setNewName] = useState('');
  const key = `cert-${r.code}`;
  return (
    <tr className="border-t border-slate-800 align-top">
      <td className="px-3 py-2">
        <div className="font-mono text-slate-200">{r.code}</div>
        <div className="text-xs text-slate-400">{r.tier === 'verified' ? 'Verified Competency' : 'Completion'}</div>
        <div className="flex gap-2 mt-1 text-xs">
          <a href={r.verify_url} target="_blank" rel="noopener" className="text-cyan-400">verify</a>
          <a href={`${API_BASE}${r.pdf_url}`} target="_blank" rel="noopener" className="text-cyan-400">pdf</a>
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="text-slate-200">{r.learner_name}</div>
        <div className="text-xs text-slate-400">{r.email}</div>
      </td>
      <td className="px-3 py-2 text-slate-300">
        {fmt(r.issued_at)}
        {r.exam_date && <div className="text-xs text-slate-400">examined {r.exam_date}</div>}
        <div className="text-xs text-slate-500">{r.email_sent_at ? 'emailed' : 'email not sent'}</div>
      </td>
      <td className="px-3 py-2">
        <span className={`text-xs px-2 py-1 rounded-full border ${r.status === 'issued' ? 'border-emerald-700 text-emerald-200' : 'border-red-900 text-red-300'}`}>
          {r.status}
        </span>
        {!r.signature_valid && <div className="text-xs text-amber-300 mt-1">signature INVALID</div>}
        {r.revoke_reason && <div className="text-xs text-slate-400 mt-1">{r.revoke_reason}</div>}
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-col gap-1">
          {r.status === 'issued' ? (
            <div className="flex items-center gap-1">
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason"
                className="w-32 rounded bg-slate-950/70 border border-slate-800 px-2 py-1 text-white text-xs"
              />
              <button
                type="button"
                disabled={busy === key || reason.length < 3}
                className="btn-ghost text-xs text-red-300"
                onClick={() =>
                  run(
                    key,
                    () =>
                      api(`/api/admin/academy/certification/certificates/${r.code}/revoke`, {
                        method: 'POST',
                        body: JSON.stringify({ reason }),
                      }),
                    `${r.code} revoked.`
                  )
                }
              >
                Revoke
              </button>
            </div>
          ) : null}
          <div className="flex items-center gap-1">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Corrected name (optional)"
              className="w-40 rounded bg-slate-950/70 border border-slate-800 px-2 py-1 text-white text-xs"
            />
            <button
              type="button"
              disabled={busy === key}
              className="btn-ghost text-xs"
              onClick={() =>
                run(
                  key,
                  () =>
                    api(`/api/admin/academy/certification/certificates/${r.code}/reissue`, {
                      method: 'POST',
                      body: JSON.stringify({ learner_name: newName || null, resend_email: true }),
                    }),
                  `${r.code} re-issued and emailed.`
                )
              }
            >
              {r.status === 'revoked' ? 'Reinstate & re-issue' : 'Re-issue'}
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}
