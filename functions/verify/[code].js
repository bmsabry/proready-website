/**
 * GET /verify/<code> — the public credential page, with crawler-grade meta.
 *
 * The SPA renders the page for humans; this function exists for LinkedIn,
 * Slack, iMessage and search crawlers, which read the HTML head and never
 * run the app. It serves the same SPA shell (`/index.html` from the ASSETS
 * binding) with the <title>, description and Open Graph / Twitter tags
 * rewritten to describe THIS credential — holder, course, tier — and with
 * og:image pointing at the certificate's own PNG, so a shared verification
 * link previews as the certificate itself.
 *
 * Failure mode is deliberate: any API hiccup (cold start, timeout, unknown
 * code) serves the untouched shell, which the app then fills in client-side.
 * A crawler gets the generic site card; a person still gets the page.
 */
const API_BASE = 'https://proreadyengineer-training-api-jd9a.onrender.com';
const SITE = 'https://proreadyengineer.com';
const API_TIMEOUT_MS = 6000;

const TIER_BLURB = {
  completion:
    'completed every lesson of the programme and passed every module evaluation and mastery check, as verified by the ProReadyEngineer learning platform.',
  verified:
    'completed the programme, passed an advanced written examination, and was examined live, one-on-one by the instructor, who attested to a verified command of every key principle of the subject.',
};

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function lookup(code) {
  const init = { headers: { Accept: 'application/json' } };
  if (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
    init.signal = AbortSignal.timeout(API_TIMEOUT_MS);
  }
  const res = await fetch(`${API_BASE}/api/academy/verify/${encodeURIComponent(code)}`, init);
  if (!res.ok) return null;
  return res.json();
}

export async function onRequestGet(context) {
  const { request, env, params } = context;
  const code = String(params.code || '').toUpperCase();
  const url = new URL(request.url);

  // The SPA shell. Pages serves `/` as the prerendered home page; its head
  // carries the site's default meta which we replace below.
  const shell = await env.ASSETS.fetch(new Request(`${url.origin}/`, { headers: { Accept: 'text/html' } }));
  if (!shell.ok) return shell;

  let cert = null;
  if (/^PRE-[CV]-[0-9A-F]{4}-[0-9A-F]{4}$/.test(code) || /^PRE-[0-9A-F]{10}$/.test(code)) {
    try {
      cert = await lookup(code);
    } catch (_) {
      cert = null;
    }
  }

  const pageUrl = `${SITE}/verify/${esc(code)}`;
  let title;
  let description;
  let image;
  if (cert && cert.valid) {
    title = `${cert.title} — ${cert.learner_name} | ProReadyEngineer LLC`;
    description = `${cert.learner_name} holds the ProReadyEngineer ${cert.title} in ${cert.course}, issued ${
      cert.issued_at ? new Date(cert.issued_at).toDateString().slice(4) : ''
    }. Credential ${cert.code}: the holder ${TIER_BLURB[cert.tier] || ''} Digitally signed and publicly verifiable.`;
    image = cert.has_preview
      ? `${API_BASE}/api/academy/verify/${encodeURIComponent(cert.code)}/certificate.png`
      : `${SITE}/Banner.png`;
  } else {
    title = 'Credential verification | ProReadyEngineer LLC';
    description = 'Verify a ProReadyEngineer training credential by its ID.';
    image = `${SITE}/Banner.png`;
  }

  const meta = {
    'name:description': description,
    'name:twitter:title': title,
    'name:twitter:description': description,
    'name:twitter:image': image,
    'name:twitter:card': 'summary_large_image',
    'property:og:title': title,
    'property:og:description': description,
    'property:og:url': pageUrl,
    'property:og:image': image,
    'property:og:type': 'website',
  };
  const seen = new Set();

  class MetaHandler {
    element(el) {
      const key = el.getAttribute('property')
        ? `property:${el.getAttribute('property')}`
        : el.getAttribute('name')
          ? `name:${el.getAttribute('name')}`
          : null;
      if (key && key in meta) {
        el.setAttribute('content', meta[key]);
        seen.add(key);
      }
    }
  }
  class HeadHandler {
    element(el) {
      // Children (the meta handlers) run before </head>, so add whatever the
      // shell did not already carry at the end tag, not at the start tag.
      el.onEndTag((end) => {
        for (const [key, value] of Object.entries(meta)) {
          if (seen.has(key)) continue;
          const [attr, name] = key.split(/:(.+)/);
          end.before(`<meta ${attr}="${esc(name)}" content="${esc(value)}">`, { html: true });
        }
        end.before('<meta name="robots" content="noindex,nofollow">', { html: true });
      });
    }
  }
  class TitleHandler {
    element(el) {
      el.setInnerContent(title);
    }
  }
  class CanonicalHandler {
    element(el) {
      el.setAttribute('href', pageUrl);
    }
  }

  const rewritten = new HTMLRewriter()
    .on('title', new TitleHandler())
    .on('meta', new MetaHandler())
    .on('link[rel="canonical"]', new CanonicalHandler())
    .on('head', new HeadHandler())
    .transform(shell);

  const headers = new Headers(rewritten.headers);
  headers.set('Cache-Control', 'public, max-age=300');
  headers.set('X-Robots-Tag', 'noindex');
  return new Response(rewritten.body, { status: 200, headers });
}
