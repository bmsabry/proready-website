import React, { useState } from 'react';
import { FileQuestion, LifeBuoy, RotateCcw, Send } from 'lucide-react';
import { academy, ApiError, type CourseSupport } from '../../lib/academyApi';

/* Course support — the three self-service actions on every course dashboard.
 *
 *   Start over               applied at once (after typing RESET): the
 *                            learner's progress, quiz results and quiz-app
 *                            state for this course are cleared; an earned
 *                            certificate is kept.
 *   Request completion marks emailed to the instructor; approved in the
 *                            admin panel, after which the certificate issues.
 *   Request the answer key   same route; on approval the PDF is emailed.
 *
 * The API says which of the three apply to this learner right now
 * (`support` on the course payload) — this panel only draws that. */

const fmt = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });

const CourseSupportPanel: React.FC<{
  code: string;
  courseTitle: string;
  support: CourseSupport;
  hasCertificate: boolean;
  onChanged: (support?: CourseSupport) => void;
}> = ({ code, courseTitle, support, hasCertificate, onChanged }) => {
  const [open, setOpen] = useState<'' | 'reset' | 'completion' | 'answers'>('');
  const [confirm, setConfirm] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState('');

  const say = (m: string) => {
    setFlash(m);
    window.setTimeout(() => setFlash(''), 8000);
  };

  const toggle = (what: '' | 'reset' | 'completion' | 'answers') => {
    setOpen(open === what ? '' : what);
    setConfirm('');
    setNote('');
    setError('');
  };

  const reset = async () => {
    setBusy(true);
    setError('');
    try {
      await academy.resetCourse(code, confirm);
      setOpen('');
      say('The course is reset to its starting point.');
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reset the course.');
    } finally {
      setBusy(false);
    }
  };

  const request = async (kind: 'completion' | 'answers') => {
    setBusy(true);
    setError('');
    try {
      const res = await academy.requestSupport(code, kind, note);
      setOpen('');
      say('Sent. The instructor will review your request and you will hear back by email.');
      onChanged(res.support);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send your request.');
    } finally {
      setBusy(false);
    }
  };

  const pendingCompletion = support.pending.completion;
  const pendingAnswers = support.pending.answers;

  return (
    <section className="card p-6 mt-8" aria-labelledby="course-support">
      <div className="flex items-start gap-4">
        <LifeBuoy className="w-8 h-8 text-cyan-400 shrink-0" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <h2 id="course-support" className="font-semibold text-white">
            Need something for this course?
          </h2>
          <p className="text-sm text-slate-300 mt-1">
            Repeat the course from the start, or ask the instructor directly. Requests are answered
            by email.
          </p>
          {flash && <p className="mt-3 text-sm text-cyan-300">{flash}</p>}
          {error && <p className="mt-3 text-sm text-red-300">{error}</p>}

          <div className="mt-5 divide-y divide-slate-800">
            {/* ---- 1. Start over ---- */}
            <div className="py-4 first:pt-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-white">Start the course over</div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    Clears your progress, quiz results and quiz-app state for this course so you can
                    repeat it{hasCertificate ? '. Your certificate stays yours.' : '.'}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn-secondary text-sm py-2 px-4"
                  onClick={() => toggle('reset')}
                  disabled={busy}
                >
                  <RotateCcw className="w-4 h-4" aria-hidden="true" /> Start over
                </button>
              </div>
              {open === 'reset' && (
                <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
                  <p className="text-sm text-amber-200">
                    This cannot be undone. Type <span className="font-mono">RESET</span> to confirm
                    starting <span className="text-white">{courseTitle}</span> over.
                  </p>
                  <div className="mt-3 flex flex-col sm:flex-row gap-3">
                    <input
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      className="flex-1 rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500"
                      placeholder="RESET"
                      aria-label="Type RESET to confirm"
                    />
                    <button
                      type="button"
                      className="btn-primary text-sm py-2 px-4"
                      disabled={busy || confirm.trim().toUpperCase() !== 'RESET'}
                      onClick={() => void reset()}
                    >
                      {busy ? 'Resetting…' : 'Reset my progress'}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* ---- 2. Completion marks ---- */}
            {support.completion_request_available && (
              <div className="py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-white">Request completion marks</div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      Lost your answers to a problem with the site? Ask the instructor to mark every
                      requirement complete so your certificate can be issued.
                    </div>
                  </div>
                  {pendingCompletion ? (
                    <span className="text-xs font-mono uppercase tracking-widest text-amber-300">
                      Sent {fmt(pendingCompletion.created_at)} · awaiting the instructor
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn-secondary text-sm py-2 px-4"
                      onClick={() => toggle('completion')}
                      disabled={busy}
                    >
                      <Send className="w-4 h-4" aria-hidden="true" /> Request completion marks
                    </button>
                  )}
                </div>
                {open === 'completion' && (
                  <RequestForm
                    note={note}
                    setNote={setNote}
                    busy={busy}
                    placeholder="What happened? e.g. the quiz page froze and my answers were lost"
                    label="Send the request"
                    onSend={() => void request('completion')}
                  />
                )}
              </div>
            )}

            {/* ---- 3. Answer key ---- */}
            <div className="py-4 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-white">Request the answer key</div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    Every module evaluation and mastery check with the answers and explanations, as a
                    PDF emailed to you once the instructor approves.
                  </div>
                </div>
                {pendingAnswers ? (
                  <span className="text-xs font-mono uppercase tracking-widest text-amber-300">
                    Sent {fmt(pendingAnswers.created_at)} · awaiting the instructor
                  </span>
                ) : support.answers_request_available ? (
                  <button
                    type="button"
                    className="btn-secondary text-sm py-2 px-4"
                    onClick={() => toggle('answers')}
                    disabled={busy}
                  >
                    <FileQuestion className="w-4 h-4" aria-hidden="true" /> Request the answer key
                  </button>
                ) : null}
              </div>
              {!support.answers_request_available && !pendingAnswers && (
                <p className="mt-2 text-xs text-slate-500">{support.answers_blocked_reason}</p>
              )}
              {open === 'answers' && (
                <RequestForm
                  note={note}
                  setNote={setNote}
                  busy={busy}
                  placeholder="Anything the instructor should know (optional)"
                  label="Send the request"
                  onSend={() => void request('answers')}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

const RequestForm = ({
  note,
  setNote,
  busy,
  placeholder,
  label,
  onSend,
}: {
  note: string;
  setNote: (v: string) => void;
  busy: boolean;
  placeholder: string;
  label: string;
  onSend: () => void;
}) => (
  <div className="mt-3">
    <textarea
      value={note}
      onChange={(e) => setNote(e.target.value)}
      rows={2}
      maxLength={1000}
      className="w-full rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
      placeholder={placeholder}
    />
    <div className="mt-2 flex items-center gap-3">
      <button type="button" className="btn-primary text-sm py-2 px-4" disabled={busy} onClick={onSend}>
        {busy ? 'Sending…' : label}
      </button>
      <span className="text-xs text-slate-500">The instructor receives it by email right away.</span>
    </div>
  </div>
);

export default CourseSupportPanel;
