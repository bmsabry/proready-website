/**
 * Past cohorts — everyone who attended a previous delivery of this course.
 *
 * An attended registration is a past-cohort record, not an active seat: it
 * is off the seat count, out of every automatic notice (date changes,
 * session reminders, confirm-your-seat chases) and off the Registrations
 * tab. This is where those people live, grouped by the cohort they sat
 * (the span on their Certificate of Attendance). Writing to them is a
 * deliberate act: the "Past attendees" audience in Comms.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { History, Mail, Undo2 } from 'lucide-react';
import { api, formatDate, reportError, type Registration } from './lib';
import { ConfirmButton, Notice, RefreshButton, Section } from './ui';

type Group = { key: string; label: string; rows: Registration[] };

const fmt = (iso: string | null | undefined) => (iso ? formatDate(iso) : '');

export default function PastCohortsTab({
  code,
  onAuthError,
  onSeatsChanged,
  gotoComms,
}: {
  code: string;
  onAuthError: () => void;
  onSeatsChanged: () => void;
  gotoComms: () => void;
}) {
  const [rows, setRows] = useState<Registration[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await api<Registration[]>(`/api/admin/registrations?course=${encodeURIComponent(code)}&scope=past`));
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setLoading(false);
    }
  }, [code, onAuthError]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo<Group[]>(() => {
    const by = new Map<string, Group>();
    for (const r of rows ?? []) {
      const start = r.attended_cohort_start ?? (r.attended_at ? r.attended_at.slice(0, 10) : '');
      const end = r.attended_cohort_end ?? '';
      const key = start || 'unknown';
      const label = start
        ? end && end !== start
          ? `Cohort ${formatDate(start)} – ${formatDate(end)}`
          : `Cohort ${formatDate(start)}`
        : 'Cohort dates not recorded';
      if (!by.has(key)) by.set(key, { key, label, rows: [] });
      by.get(key)!.rows.push(r);
    }
    // Newest cohort first.
    return [...by.values()].sort((a, b) => (a.key < b.key ? 1 : a.key > b.key ? -1 : 0));
  }, [rows]);

  /** Undo a mistaken attendance mark: the row returns to Registrations (and
   *  the seat count) and its Certificate of Attendance is revoked. */
  async function withdraw(r: Registration) {
    setBusyId(r.id);
    setError(null);
    try {
      await api('/api/admin/mark-attended', {
        method: 'POST',
        body: JSON.stringify({ registration_id: r.id, attended: false }),
      });
      setRows((prev) => (prev ? prev.filter((x) => x.id !== r.id) : prev));
      setFlash(`${r.full_name} moved back to Registrations; the attendance certificate was revoked.`);
      onSeatsChanged();
    } catch (e) {
      reportError(e, onAuthError, setError);
    } finally {
      setBusyId(null);
    }
  }

  const total = rows?.length ?? 0;

  return (
    <Section
      icon={<History className="w-5 h-5 text-cyan-400" />}
      title="Past cohorts"
      sub="People who attended a previous delivery. They hold no seat in the next cohort and receive none of its automatic notices — date changes, session reminders, confirm-your-seat chases. To write to them, use the Past attendees audience in Comms."
      actions={
        <>
          <button
            type="button"
            className="btn-secondary flex items-center gap-2 text-xs py-1.5 px-2.5"
            onClick={gotoComms}
            disabled={total === 0}
            title="Open Comms with the Past attendees audience"
          >
            <Mail className="w-3.5 h-3.5" /> Email past attendees
          </button>
          <RefreshButton onClick={() => void load()} loading={loading} small />
        </>
      }
    >
      {flash && <Notice kind="success">{flash}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {rows === null ? (
        <p className="text-slate-400 text-sm">{loading ? 'Loading…' : '—'}</p>
      ) : rows.length === 0 ? (
        <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-8 text-slate-300 text-sm">
          No past cohorts yet. When a cohort ends, use <span className="text-white">Close cohort</span> on
          the Registrations tab (or <span className="text-white">Mark attended</span> per person) and the
          attendees appear here.
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => (
            <div key={g.key} className="bg-slate-900/70 border border-slate-800 rounded-2xl overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-slate-800">
                <div className="text-white font-semibold">{g.label}</div>
                <div className="text-xs font-mono uppercase tracking-wider text-slate-400">
                  {g.rows.length} attended
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400 uppercase tracking-wide">
                      <th className="px-4 py-2">Name</th>
                      <th className="px-4 py-2">Email</th>
                      <th className="px-4 py-2">Company</th>
                      <th className="px-4 py-2">Marked attended</th>
                      <th className="px-4 py-2">Certificate</th>
                      <th className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody className="text-slate-200">
                    {g.rows.map((r) => (
                      <tr key={r.id} className="border-t border-slate-800/70">
                        <td className="px-4 py-2 whitespace-nowrap">{r.full_name}</td>
                        <td className="px-4 py-2 whitespace-nowrap">{r.email}</td>
                        <td className="px-4 py-2">{r.company}</td>
                        <td className="px-4 py-2 whitespace-nowrap">{fmt(r.attended_at)}</td>
                        <td className="px-4 py-2 font-mono text-xs">
                          {r.attendance_certificate_code ? (
                            <a
                              href={`/verify/${r.attendance_certificate_code}`}
                              target="_blank"
                              rel="noopener"
                              className="text-cyan-400 hover:text-cyan-300"
                            >
                              {r.attendance_certificate_code}
                            </a>
                          ) : (
                            <span className="text-slate-500">—</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right whitespace-nowrap">
                          <ConfirmButton
                            message={`Move ${r.full_name} back to Registrations? Their attendance record is withdrawn and the Certificate of Attendance revoked; they will count as an active registrant again and receive the cohort's notices.`}
                            onConfirm={() => void withdraw(r)}
                            disabled={busyId === r.id}
                            className="btn-ghost text-xs py-1 px-2 inline-flex items-center gap-1"
                            title="Undo the attendance mark"
                          >
                            <Undo2 className="w-3.5 h-3.5" /> Withdraw
                          </ConfirmButton>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
