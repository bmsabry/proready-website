/**
 * Learner requests — completion marks and answer keys, every course.
 *
 * A learner asks from their course dashboard; the owner gets an email that
 * links here. Approve applies the effect at once (completion → every
 * requirement marked done and the certificate issued; answers → the PDF
 * emailed). Decline sends the learner the note. Nothing in the email itself
 * can approve — only this panel, signed in.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Check, Inbox, X } from 'lucide-react';
import { api, reportError } from './lib';
import { Notice, RefreshButton, Section } from './ui';

type Progress = {
  lessons_done: number;
  lessons_total: number;
  sets_passed: number;
  sets_total: number;
  complete: boolean;
};

type Cohort = {
  course_code: string;
  course_title: string;
  registration_status: string;
  attendance_confirmed: boolean;
} | null;

export type LearnerRequestRow = {
  id: number;
  kind: 'completion' | 'answers';
  kind_label: string;
  status: 'pending' | 'approved' | 'declined';
  note: string;
  decision_note: string;
  decided_by: string;
  decided_at: string | null;
  result: string;
  created_at: string;
  product_code: string;
  product_title: string;
  learner_name: string;
  learner_email: string;
  progress: Progress | null;
  cohort: Cohort;
};

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';

export default function LearnerRequestsSection({ onAuthError }: { onAuthError: () => void }) {
  const [rows, setRows] = useState<LearnerRequestRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [showDecided, setShowDecided] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<{ requests: LearnerRequestRow[]; pending: number }>(
        '/api/admin/academy/requests?limit=100'
      );
      setRows(r.requests);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (row: LearnerRequestRow, action: 'approve' | 'decline') => {
    const note = notes[row.id] ?? '';
    if (action === 'decline' && !note.trim()) {
      setError('Say why in the note — the learner receives it.');
      return;
    }
    setBusy(row.id);
    setError(null);
    try {
      const updated = await api<LearnerRequestRow>(
        `/api/admin/academy/requests/${row.id}/${action}`,
        { method: 'POST', body: JSON.stringify({ note }) }
      );
      setRows((prev) => (prev ?? []).map((r) => (r.id === row.id ? updated : r)));
      const what =
        action === 'decline'
          ? 'Declined — the learner has your note.'
          : updated.kind === 'answers'
            ? updated.result === 'answer_key_sent'
              ? 'Approved — the answer key was emailed.'
              : 'Approved, but the email did not go out. Check the comms log.'
            : updated.result === 'awaiting_name'
              ? 'Approved — requirements marked complete; the certificate issues once the learner adds their name.'
              : `Approved — certificate ${updated.result} issued and emailed.`;
      setFlash(what);
      window.setTimeout(() => setFlash(null), 8000);
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusy(null);
    }
  };

  const pending = (rows ?? []).filter((r) => r.status === 'pending');
  const decided = (rows ?? []).filter((r) => r.status !== 'pending');

  return (
    <Section
      icon={<Inbox className="w-5 h-5 text-cyan-400" />}
      title={
        <>
          Learner requests
          {pending.length > 0 && (
            <span className="ml-1 text-xs font-mono px-2 py-0.5 rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-300">
              {pending.length} pending
            </span>
          )}
        </>
      }
      sub="Completion marks and answer keys asked for from the course dashboards. Approving applies the effect immediately; declining sends the learner your note."
      actions={<RefreshButton onClick={() => void load()} loading={loading} />}
    >
      {error && <Notice kind="error">{error}</Notice>}
      {flash && (
        <Notice kind="success">
          <span className="inline-flex items-center gap-2">
            <Check className="w-4 h-4" />
            {flash}
          </span>
        </Notice>
      )}

      {rows === null ? (
        <p className="text-slate-400 text-sm">{loading ? 'Loading…' : '—'}</p>
      ) : pending.length === 0 ? (
        <p className="text-slate-400 text-sm">Nothing waiting for you.</p>
      ) : (
        <div className="space-y-3">
          {pending.map((r) => (
            <div key={r.id} className="bg-slate-900/70 border border-amber-500/20 rounded-xl p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-white font-semibold">
                    {r.learner_name || r.learner_email}{' '}
                    <span className="text-slate-400 font-normal">asks for {r.kind_label}</span>
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    {r.learner_email} · {r.product_title} · #{r.id} · {when(r.created_at)}
                  </div>
                </div>
                <span className="text-[11px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border border-slate-600 text-slate-300">
                  {r.cohort ? 'live cohort' : 'self-study'}
                </span>
              </div>

              <dl className="mt-3 grid sm:grid-cols-2 gap-x-6 gap-y-1 text-sm">
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-slate-400">Standing</dt>
                  <dd className="text-slate-200">
                    {r.progress
                      ? `${r.progress.lessons_done} of ${r.progress.lessons_total} lessons · ${r.progress.sets_passed} of ${r.progress.sets_total} evaluations passed${r.progress.complete ? ' · complete' : ''}`
                      : '—'}
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-slate-400">Access</dt>
                  <dd className="text-slate-200">
                    {r.cohort
                      ? `Live-cohort registrant${r.cohort.course_title ? ` — ${r.cohort.course_title}` : ''} (${r.cohort.registration_status}${r.cohort.attendance_confirmed ? ', attendance confirmed' : ''})`
                      : 'Self-study — no live-cohort registration on file'}
                  </dd>
                </div>
                {r.note && (
                  <div className="flex gap-2 sm:col-span-2">
                    <dt className="w-20 shrink-0 text-slate-400">Their note</dt>
                    <dd className="text-slate-200 italic">{r.note}</dd>
                  </div>
                )}
              </dl>

              <div className="mt-3 flex flex-col sm:flex-row gap-2 sm:items-center">
                <input
                  value={notes[r.id] ?? ''}
                  onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })}
                  maxLength={1000}
                  placeholder="Note to the learner (required to decline; optional to approve)"
                  className="flex-1 rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white text-sm"
                />
                <button
                  type="button"
                  className="btn-primary text-sm py-2 px-4"
                  disabled={busy === r.id}
                  onClick={() => void decide(r, 'approve')}
                >
                  <Check className="w-4 h-4" aria-hidden="true" />
                  {busy === r.id ? 'Working…' : r.kind === 'completion' ? 'Approve and issue certificate' : 'Approve and email the key'}
                </button>
                <button
                  type="button"
                  className="btn-ghost text-sm py-2 px-4"
                  disabled={busy === r.id}
                  onClick={() => void decide(r, 'decline')}
                >
                  <X className="w-4 h-4" aria-hidden="true" /> Decline
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {decided.length > 0 && (
        <div className="mt-4">
          <button
            type="button"
            className="text-xs text-slate-400 hover:text-white underline-offset-2 hover:underline"
            onClick={() => setShowDecided(!showDecided)}
          >
            {showDecided ? 'Hide' : 'Show'} the last {decided.length} decided
          </button>
          {showDecided && (
            <div className="mt-2 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-400 uppercase tracking-wide">
                    <th className="py-1 pr-4">When</th>
                    <th className="py-1 pr-4">Learner</th>
                    <th className="py-1 pr-4">Course</th>
                    <th className="py-1 pr-4">Request</th>
                    <th className="py-1 pr-4">Decision</th>
                    <th className="py-1 pr-4">Result</th>
                  </tr>
                </thead>
                <tbody className="text-slate-200">
                  {decided.map((r) => (
                    <tr key={r.id} className="border-t border-slate-800">
                      <td className="py-1.5 pr-4 whitespace-nowrap">{when(r.decided_at)}</td>
                      <td className="py-1.5 pr-4">{r.learner_name || r.learner_email}</td>
                      <td className="py-1.5 pr-4">{r.product_title}</td>
                      <td className="py-1.5 pr-4">{r.kind_label}</td>
                      <td className="py-1.5 pr-4">
                        {r.status}
                        {r.decision_note ? ` — ${r.decision_note}` : ''}
                      </td>
                      <td className="py-1.5 pr-4 font-mono text-xs">{r.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
