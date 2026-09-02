import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Award,
  BadgeCheck,
  Download,
  KeyRound,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { usePageMeta } from '../lib/meta';
import { academy, ApiError, certificateFileUrl, VerifyResult } from '../lib/academyApi';

/* Public credential verification — /verify/:code
 *
 * This is the page a hiring manager lands on from the QR code, the LinkedIn
 * post or the "Verify at" line on the certificate. It shows the certificate
 * image, exactly what was attested, and the integrity checks (Ed25519
 * signature over the facts; SHA-256 of the file). No login. */

const fmtDate = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '—';

const Verify: React.FC = () => {
  const { code = '' } = useParams();
  const [data, setData] = useState<VerifyResult | null>(null);
  const [error, setError] = useState('');
  const isSample = code.toUpperCase() === 'SAMPLE';

  const title = data?.valid
    ? `${data.title} — ${data.learner_name}`
    : 'Credential verification';
  usePageMeta(
    title,
    data?.valid
      ? `${data.learner_name} holds the ProReadyEngineer ${data.title} in ${data.course}, issued ${fmtDate(
          data.issued_at
        )}. Credential ${data.code}, digitally signed and verified.`
      : 'Verify a ProReadyEngineer training credential by its ID.',
    {
      noindex: true,
      image: data?.valid && data.has_preview ? certificateFileUrl(data.code, 'png') : undefined,
    }
  );

  useEffect(() => {
    if (isSample) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await academy.verifyCertificate(code);
        if (!cancelled) setData(res);
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof ApiError ? err.message : 'Could not reach the verification service.'
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, isSample]);

  const Shell = ({ children }: { children: React.ReactNode }) => (
    <div className="relative pt-32 pb-24">
      <div className="hero-backdrop" />
      <div className="absolute inset-0 -z-10 bg-hero-radial" />
      <div className="container-site max-w-5xl">
        <span className="eyebrow">Credential verification</span>
        {children}
      </div>
    </div>
  );

  if (isSample) {
    return (
      <Shell>
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight mt-3">
          This is a <span className="text-gradient">sample</span> certificate
        </h1>
        <p className="text-slate-300 mt-3 max-w-2xl">
          The specimen you scanned is shown on our course pages to illustrate what graduates
          receive. It was not issued to anyone. Real certificates carry a credential ID of the
          form PRE-C-XXXX-XXXX or PRE-V-XXXX-XXXX and resolve to the holder's record on this page.
        </p>
        <Link to="/training" className="btn-secondary mt-6">
          Browse the training catalog
        </Link>
      </Shell>
    );
  }

  if (error) {
    return (
      <Shell>
        <h1 className="text-3xl font-bold tracking-tight mt-3">Verification unavailable</h1>
        <p className="text-slate-300 mt-3">{error}</p>
      </Shell>
    );
  }

  if (!data) {
    return (
      <Shell>
        <p className="mt-6 font-mono text-sm uppercase tracking-widest text-cyan-400 animate-pulse">
          Checking credential {code.toUpperCase()}…
        </p>
      </Shell>
    );
  }

  if (!data.valid && !data.status) {
    return (
      <Shell>
        <div className="flex items-center gap-3 mt-3">
          <XCircle className="w-8 h-8 text-amber-400" aria-hidden="true" />
          <h1 className="text-3xl font-bold tracking-tight">No credential with this ID</h1>
        </div>
        <p className="text-slate-300 mt-3 max-w-2xl">
          <span className="font-mono text-white">{data.code}</span> does not match any credential
          issued by ProReadyEngineer LLC. Check the ID on the certificate — it has the form
          PRE-C-XXXX-XXXX or PRE-V-XXXX-XXXX — or contact info@proreadyengineer.com.
        </p>
      </Shell>
    );
  }

  const verified = data.tier === 'verified';
  const revoked = data.status === 'revoked';
  const tampered = !revoked && data.signature_valid === false;

  return (
    <Shell>
      <div className="flex flex-wrap items-center gap-3 mt-3">
        {data.valid ? (
          <ShieldCheck className="w-9 h-9 text-cyan-400 shrink-0" aria-hidden="true" />
        ) : (
          <ShieldAlert className="w-9 h-9 text-amber-400 shrink-0" aria-hidden="true" />
        )}
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
          {data.valid ? (
            <>
              Credential <span className="text-gradient">verified</span>
            </>
          ) : revoked ? (
            'Credential revoked'
          ) : (
            'Credential could not be verified'
          )}
        </h1>
      </div>
      {revoked && (
        <p className="mt-3 text-amber-200">
          This credential was revoked by the issuer{data.revoke_reason ? `: ${data.revoke_reason}` : '.'}
        </p>
      )}
      {tampered && (
        <p className="mt-3 text-amber-200">
          The record's digital signature does not match its contents. Treat this credential as
          invalid and contact info@proreadyengineer.com.
        </p>
      )}

      <div className="grid lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] gap-8 mt-8 items-start">
        <div>
          {data.valid && data.has_preview ? (
            <a
              href={certificateFileUrl(data.code, 'pdf')}
              target="_blank"
              rel="noopener"
              className="block rounded-lg overflow-hidden border border-slate-700/70 bg-white shadow-glow-cyan"
            >
              <img
                src={certificateFileUrl(data.code, 'png')}
                alt={`${data.title} issued to ${data.learner_name} for ${data.course}`}
                className="w-full h-auto block"
              />
            </a>
          ) : (
            <div className="card p-8 text-center text-slate-500 text-sm">
              Certificate image not available for this record.
            </div>
          )}
          {data.valid && data.has_pdf && (
            <a
              href={certificateFileUrl(data.code, 'pdf')}
              className="btn-secondary mt-4"
              target="_blank"
              rel="noopener"
            >
              <Download className="w-4 h-4" aria-hidden="true" /> Open the PDF
            </a>
          )}
        </div>

        <div className="space-y-6">
          <div className="card p-6">
            <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-cyan-400">
              {verified ? (
                <BadgeCheck className="w-4 h-4" aria-hidden="true" />
              ) : (
                <Award className="w-4 h-4" aria-hidden="true" />
              )}
              {data.title}
            </div>
            <h2 className="text-2xl font-semibold text-white mt-2">{data.learner_name}</h2>
            <dl className="mt-4 text-sm space-y-2">
              <div className="grid grid-cols-[110px_1fr] gap-2">
                <dt className="text-slate-400">Course</dt>
                <dd className="text-white">{data.course}</dd>
              </div>
              <div className="grid grid-cols-[110px_1fr] gap-2">
                <dt className="text-slate-400">Issued</dt>
                <dd className="text-white">{fmtDate(data.issued_at)}</dd>
              </div>
              {verified && (
                <>
                  <div className="grid grid-cols-[110px_1fr] gap-2">
                    <dt className="text-slate-400">Examined</dt>
                    <dd className="text-white">
                      {fmtDate(data.exam_date)} — live, one-on-one oral examination of{' '}
                      {data.exam_minutes} minutes by video conference
                    </dd>
                  </div>
                  <div className="grid grid-cols-[110px_1fr] gap-2">
                    <dt className="text-slate-400">Examiner</dt>
                    <dd className="text-white">{data.instructor}</dd>
                  </div>
                </>
              )}
              <div className="grid grid-cols-[110px_1fr] gap-2">
                <dt className="text-slate-400">Credential ID</dt>
                <dd className="font-mono text-white">{data.code}</dd>
              </div>
              <div className="grid grid-cols-[110px_1fr] gap-2">
                <dt className="text-slate-400">Issuer</dt>
                <dd className="text-white">{data.issuer}</dd>
              </div>
            </dl>
            <p className="text-sm text-slate-300 mt-4">
              {verified
                ? 'Attests that the holder completed the full programme, all module evaluations and mastery checks, passed an advanced written examination, and was then examined live by the instructor, who confirmed a sound grasp of every key principle of the subject.'
                : 'Attests that the holder completed every lesson of the programme and passed every module evaluation and mastery check at or above the 80% mastery threshold, as verified by the ProReadyEngineer learning platform.'}
            </p>
            {verified && (data.competencies?.length ?? 0) > 0 && (
              <div className="mt-4">
                <div className="text-xs font-mono uppercase tracking-widest text-slate-400">
                  Principles examined
                </div>
                <ol className="mt-2 text-sm text-slate-300 space-y-1 list-decimal list-inside">
                  {data.competencies!.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ol>
              </div>
            )}
          </div>

          <div className="card p-6">
            <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-slate-400">
              <KeyRound className="w-4 h-4" aria-hidden="true" /> Integrity
            </div>
            <ul className="mt-3 text-sm space-y-2">
              <li className="flex items-start gap-2">
                {data.signature_valid ? (
                  <ShieldCheck className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" aria-hidden="true" />
                ) : (
                  <ShieldAlert className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" aria-hidden="true" />
                )}
                <span className="text-slate-300">
                  Digital signature (Ed25519) over the holder, course, tier and dates:{' '}
                  <span className="text-white">{data.signature_valid ? 'valid' : 'INVALID'}</span>
                  <br />
                  <span className="font-mono text-xs text-slate-400">
                    fingerprint {data.signature_fingerprint} · key {data.signing_key_id}
                  </span>
                </span>
              </li>
              <li className="flex items-start gap-2">
                <ShieldCheck className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" aria-hidden="true" />
                <span className="text-slate-300">
                  PDF file SHA-256 (compare against a downloaded copy):
                  <br />
                  <span className="font-mono text-xs text-slate-400 break-all">{data.pdf_sha256}</span>
                </span>
              </li>
              <li className="text-xs text-slate-500 pt-1">
                Issuer public key (base64): <span className="font-mono break-all">{data.public_key_b64}</span>
              </li>
            </ul>
          </div>

          <p className="text-xs text-slate-500">
            ProReadyEngineer LLC · 5325 Deerfield Blvd #148, Mason, OH 45040, USA · +1 (513)
            849-1016 · info@proreadyengineer.com. This certificate attests to the holder's
            demonstrated understanding in the assessment described; it is not a professional
            engineering licence.
          </p>
        </div>
      </div>
    </Shell>
  );
};

export default Verify;
