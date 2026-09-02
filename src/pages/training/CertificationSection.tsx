import React from 'react';
import { Award, BadgeCheck, Check, Linkedin, QrCode, ShieldCheck } from 'lucide-react';
import { Reveal } from '../../components/ui';

/* Certification section for every course advertisement page.
 *
 * Two tiers, shown side by side with a SAMPLE specimen of each, so a
 * prospective learner sees exactly what they will hold at the end. The copy
 * is shared across courses; the examined-tier price and its availability
 * are per course. */

type Props = {
  courseTitle: string;
  /* Price of the examined tier, e.g. "$300". */
  examinedPrice: string;
  /* False when the examined tier is not offered on this course yet. */
  examinedAvailable?: boolean;
};

const CertificationSection: React.FC<Props> = ({
  courseTitle,
  examinedPrice,
  examinedAvailable = true,
}) => (
  <section id="certification" className="section-pad bg-slate-950/40 scroll-mt-24">
    <div className="container-site">
      <Reveal className="text-center max-w-3xl mx-auto mb-12">
        <span className="eyebrow">Certification</span>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight mt-4">
          Two credentials. One is included, the other is{' '}
          <span className="text-gradient">earned in front of the instructor</span>.
        </h2>
        <p className="text-slate-300 leading-relaxed mt-4">
          Both are issued in your name, digitally signed, publicly verifiable by QR code or
          credential ID, and ready to add to your LinkedIn profile in one click. They differ in
          what they attest — and in who did the attesting.
        </p>
      </Reveal>

      <div className="grid lg:grid-cols-2 gap-8 max-w-6xl mx-auto items-stretch">
        {/* ---- Tier 1 ---- */}
        <Reveal className="card overflow-hidden flex flex-col">
          <a
            href="/certificates/sample-completion.jpg"
            target="_blank"
            rel="noopener"
            className="block bg-white border-b border-slate-800"
            aria-label="Open a sample Certificate of Completion"
          >
            <img
              src="/certificates/sample-completion.jpg"
              alt={`Sample Certificate of Completion for ${courseTitle}, marked SAMPLE`}
              width={1600}
              height={1237}
              loading="lazy"
              className="w-full h-auto block"
            />
          </a>
          <div className="p-7 flex-1 flex flex-col">
            <div className="flex flex-wrap items-center gap-3">
              <Award className="w-6 h-6 text-cyan-400" aria-hidden="true" />
              <h3 className="text-xl font-semibold text-white">Certificate of Completion</h3>
              <span className="ml-auto text-xs font-mono uppercase tracking-widest px-2.5 py-1 rounded-full border border-slate-600 text-slate-300">
                Included
              </span>
            </div>
            <p className="text-slate-300 leading-relaxed mt-3">
              Issued automatically — no request, no wait — the moment you have completed every
              lesson and passed every module evaluation and mastery check at the 80% threshold.
              It states exactly that, so it means something.
            </p>
            <ul className="mt-4 space-y-2 text-sm text-slate-300">
              {[
                'Generated and emailed the instant the last requirement is met',
                'Programme, hours and modules spelled out on the certificate',
                'Unique credential ID and QR code; anyone can verify it online',
                'Add to LinkedIn profile and share buttons built in',
              ].map((t) => (
                <li key={t} className="flex gap-2">
                  <Check className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" aria-hidden="true" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </Reveal>

        {/* ---- Tier 2 ---- */}
        <Reveal delay={0.05} className="card overflow-hidden flex flex-col border-cyan-500/40 shadow-glow-cyan">
          <a
            href="/certificates/sample-verified.jpg"
            target="_blank"
            rel="noopener"
            className="block bg-white border-b border-slate-800"
            aria-label="Open a sample Certificate of Verified Competency"
          >
            <img
              src="/certificates/sample-verified.jpg"
              alt={`Sample Certificate of Verified Competency for ${courseTitle}, signed by the instructor, marked SAMPLE`}
              width={1600}
              height={1237}
              loading="lazy"
              className="w-full h-auto block"
            />
          </a>
          <div className="p-7 flex-1 flex flex-col">
            <div className="flex flex-wrap items-center gap-3">
              <BadgeCheck className="w-6 h-6 text-cyan-400" aria-hidden="true" />
              <h3 className="text-xl font-semibold text-white">Certificate of Verified Competency</h3>
              <span className="ml-auto text-xs font-mono uppercase tracking-widest px-2.5 py-1 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300">
                Instructor examined · {examinedPrice}
              </span>
            </div>
            <p className="text-slate-300 leading-relaxed mt-3">
              The credential a hiring manager can trust. After the course, you sit an advanced
              written examination and then a 60-minute live, one-on-one oral examination with
              the instructor — questions without notice, design cases not covered in the
              material, reasoning out loud. A pass issues a certificate{' '}
              <span className="text-white">signed by the instructor</span>, attesting that you
              were examined in person and demonstrated a verified command of every key
              principle of the subject, each one listed on the certificate.
            </p>
            <ul className="mt-4 space-y-2 text-sm text-slate-300">
              {[
                'Prerequisite: the Certificate of Completion',
                'Advanced written examination at analysis level, 80% pass mark',
                '60-minute oral examination by video, scheduled around your time zone',
                'Signed and issued only by the instructor after the examination',
                'One complimentary re-examination if mastery is not shown the first time',
              ].map((t) => (
                <li key={t} className="flex gap-2">
                  <Check className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" aria-hidden="true" />
                  {t}
                </li>
              ))}
            </ul>
            {!examinedAvailable && (
              <p className="mt-4 text-xs text-slate-400">
                The examined tier is opened for each course once its first learners complete; ask
                us if you would like it for this course.
              </p>
            )}
          </div>
        </Reveal>
      </div>

      <Reveal className="max-w-6xl mx-auto mt-8 grid sm:grid-cols-3 gap-4">
        {[
          {
            icon: ShieldCheck,
            t: 'Tamper-evident',
            d: 'Every certificate is signed with a cryptographic key; the verification page checks the signature and the file hash, so an altered name or date is caught.',
          },
          {
            icon: QrCode,
            t: 'Verifiable in seconds',
            d: 'Scan the QR code or type the credential ID at proreadyengineer.com/verify to see the holder, the course and exactly what was attested.',
          },
          {
            icon: Linkedin,
            t: 'LinkedIn-ready',
            d: '"Add to profile" pre-fills the Licenses & Certifications form; "Share" posts the verification page, which shows the certificate itself.',
          },
        ].map(({ icon: Icon, t, d }) => (
          <div key={t} className="flex gap-3">
            <Icon className="w-5 h-5 text-cyan-400 mt-0.5 shrink-0" aria-hidden="true" />
            <div>
              <div className="font-semibold text-white">{t}</div>
              <p className="text-sm text-slate-300 leading-relaxed mt-1">{d}</p>
            </div>
          </div>
        ))}
      </Reveal>
      <p className="text-center text-xs text-slate-500 mt-8 max-w-3xl mx-auto">
        Specimens above are marked SAMPLE and were not issued to anyone. Certificates attest to
        demonstrated understanding in the assessment described; they are not a professional
        engineering licence.
      </p>
    </div>
  </section>
);

export default CertificationSection;
