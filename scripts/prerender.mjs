/**
 * Build-time prerenderer.
 * Runs after `vite build` (client) + `vite build --ssr` (server bundle).
 * Renders every public route to static HTML with per-page head tags and
 * JSON-LD baked in, and generates dist/sitemap.xml.
 *
 * No _redirects file: Cloudflare Pages redirects SHADOW static assets, so a
 * catch-all rewrite would hijack the prerendered pages. Without _redirects,
 * Pages serves static assets first and falls back to /index.html (SPA mode)
 * for unknown paths such as /admin.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const ORIGIN = 'https://proreadyengineer.com';

// Course facts fetched from the live API before the bundle was built. Used to
// verify that what we just prerendered actually says what the backend says —
// see the "schedule check" at the bottom of this file.
const courseSnapshot = JSON.parse(readFileSync('src/data/course-snapshot.json', 'utf8'));
const { render, PRERENDER_ROUTES } = await import('../dist-ssr/entry-server.js');

const template = readFileSync('dist/index.html', 'utf8');

// dist/index.html is BOTH the template and one of the outputs (route '/'), so
// running this script twice without a fresh `vite build` in between would feed
// the already-rendered homepage back in as the template — every route would
// then be written as a copy of the homepage. Catch that loudly instead of
// silently publishing 33 identical pages.
if (template.includes('data-ssr')) {
  console.error(
    'dist/index.html is already a prerendered page, not the Vite template. ' +
      'Run `vite build` first — `npm run build` does this in the right order.',
  );
  process.exit(1);
}

const escAttr = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escJson = (o) => JSON.stringify(o).replace(/</g, '\\u003c');

function seoBlock(seo) {
  const lines = [
    `<title>${escAttr(seo.title)}</title>`,
    `<meta name="description" content="${escAttr(seo.description)}" />`,
    `<link rel="canonical" href="${seo.canonical}" />`,
    `<meta property="og:type" content="${seo.type}" />`,
    `<meta property="og:url" content="${seo.canonical}" />`,
    `<meta property="og:title" content="${escAttr(seo.title)}" />`,
    `<meta property="og:description" content="${escAttr(seo.description)}" />`,
    `<meta property="og:image" content="${seo.image}" />`,
    `<meta property="og:site_name" content="ProReadyEngineer LLC" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${escAttr(seo.title)}" />`,
    `<meta name="twitter:description" content="${escAttr(seo.description)}" />`,
    `<meta name="twitter:image" content="${seo.image}" />`,
  ];
  if (seo.noindex) lines.push('<meta name="robots" content="noindex,nofollow" />');
  for (const ld of seo.jsonLd ?? []) {
    lines.push(`<script type="application/ld+json" data-seo-jsonld>${escJson(ld)}</script>`);
  }
  return lines.join('\n    ');
}

let failures = 0;
for (const route of PRERENDER_ROUTES) {
  try {
    const { html: appHtml, seo } = await render(route.path);
    if (!appHtml || appHtml.length < 500) throw new Error(`suspiciously small render (${appHtml.length} chars)`);
    if (!seo) throw new Error('page did not register SEO metadata (usePageMeta missing?)');

    let out = template.replace(/<!-- seo:start -->[\s\S]*?<!-- seo:end -->/, () => `<!-- seo:start -->\n    ${seoBlock(seo)}\n    <!-- seo:end -->`);
    out = out.replace('<div id="root"></div>', () => `<div id="root" data-ssr="${route.path}">${appHtml}</div>`);

    // foo.html (not foo/index.html): Pages serves it at the clean URL /foo
    // with no trailing-slash redirect, preserving already-indexed URLs.
    const file = route.path === '/' ? 'dist/index.html' : join('dist', `${route.path}.html`);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, out);
    console.log(`  ✓ ${route.path} (${(appHtml.length / 1024).toFixed(1)} kB)`);
  } catch (err) {
    failures++;
    console.error(`  ✗ ${route.path}: ${err.message}`);
  }
}

// Sitemap
const urls = PRERENDER_ROUTES.map((r) => {
  const loc = ORIGIN + (r.path === '/' ? '/' : r.path);
  return `  <url><loc>${loc}</loc><lastmod>${r.lastmod}</lastmod><changefreq>${r.changefreq ?? 'monthly'}</changefreq><priority>${(r.priority ?? 0.6).toFixed(1)}</priority></url>`;
});
writeFileSync(
  'dist/sitemap.xml',
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join('\n')}\n</urlset>\n`
);
console.log(`  ✓ sitemap.xml (${PRERENDER_ROUTES.length} URLs)`);

// -----------------------------------------------------------------------------
// Render-blocking check
// -----------------------------------------------------------------------------
// Every page is prerendered to complete HTML, which is worth nothing if the
// browser refuses to paint it. A plain <link rel="stylesheet"> pointing at
// another origin blocks first paint until that origin answers — and the
// Google Fonts link did exactly that under a comment claiming it did not.
// Measured with fonts.googleapis.com unreachable, first contentful paint was
// 12.5 SECONDS on every route; a visitor on a slow or filtered link to Google
// just sees a blank page and leaves. With the link made non-blocking the same
// measurement is ~200 ms.
//
// A third-party stylesheet is allowed only when it cannot block paint:
// media="print" (flipped to all on load) or inside <noscript>.
const blockingSheet = /<link\b(?![^>]*\bmedia\s*=\s*["']print["'])[^>]*\brel\s*=\s*["']stylesheet["'][^>]*\bhref\s*=\s*["']https?:\/\/[^"']+["'][^>]*>/i;

for (const route of PRERENDER_ROUTES) {
  const file = route.path === '/' ? 'dist/index.html' : join('dist', `${route.path}.html`);
  let html;
  try {
    html = readFileSync(file, 'utf8');
  } catch {
    continue;
  }
  // <noscript> copies are fine — they only apply when scripts are off.
  const withoutNoscript = html.replace(/<noscript>[\s\S]*?<\/noscript>/gi, '');
  const hit = withoutNoscript.match(blockingSheet);
  if (hit) {
    failures++;
    console.error(
      `  ✗ ${route.path}: a third-party stylesheet blocks first paint:\n      ${hit[0].slice(0, 160)}\n` +
        `      Add media="print" onload="this.media='all'" so the page paints without waiting on it.`,
    );
  }
}
if (failures === 0) console.log('  ✓ no render-blocking third-party stylesheets');

// -----------------------------------------------------------------------------
// Schedule check
// -----------------------------------------------------------------------------
// The prerendered HTML is what crawlers and no-JS visitors read; the live API
// is the truth. Twice, a page shipped advertising a cohort that had already
// moved, because a hand-typed fallback was never updated. Course pages now
// derive their fallback from the build-time snapshot — this check proves that
// wiring is actually intact in the emitted HTML, so if anyone reintroduces a
// hardcoded date the build stops instead of quietly publishing the wrong one.
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const labelFor = (iso) => {
  const [y, m, d] = String(iso).split('-').map((n) => parseInt(n, 10));
  return `${MONTHS[m - 1]} ${d}, ${y}`;
};

// route -> { code, days }. days:'all' means the page publishes the full
// day-by-day schedule and every date must match; days:'start' means it only
// shows the cohort start.
//
// Checking every day matters: the start date alone also appears in the hero
// and the register box, so a page could keep showing the right start while its
// day-by-day timeline had silently reverted to a hardcoded list.
const SCHEDULE_PAGES = {
  '/training/gas-turbine-emissions-mapping': { code: 'gas-turbine-emissions-mapping-2026-05', days: 'all' },
  '/training/micro-gas-turbine-design-live': { code: 'micro-gas-turbine-design-2026-10', days: 'all' },
  '/training': { code: 'gas-turbine-emissions-mapping-2026-05', days: 'start' },
};

const todayIso = new Date().toISOString().slice(0, 10);
for (const [route, spec] of Object.entries(SCHEDULE_PAGES)) {
  const course = courseSnapshot.courses?.[spec.code];
  if (!course) {
    console.warn(`  ! ${route}: no snapshot for ${spec.code}; schedule check skipped.`);
    continue;
  }
  const file = route === '/' ? 'dist/index.html' : join('dist', `${route}.html`);
  let html;
  try {
    html = readFileSync(file, 'utf8');
  } catch {
    continue; // the render already failed and was counted above
  }
  const expected = labelFor(course.dayDates[0] ?? course.startDate);
  const required = spec.days === 'all' ? course.dayDates.map(labelFor) : [expected];
  const missing = required.filter((label) => !html.includes(label));
  if (missing.length > 0) {
    failures++;
    console.error(
      `  ✗ ${route}: prerendered HTML is missing ${missing.length} live cohort date(s) ` +
        `(${missing.join(', ')}). Something is publishing a hardcoded schedule instead of ` +
        `the build-time snapshot.`,
    );
  } else if ((course.dayDates[course.dayDates.length - 1] ?? course.startDate) < todayIso) {
    // Not a build failure: an unrelated deploy shouldn't be blocked because a
    // cohort ended. But it must be impossible to miss in the deploy log.
    console.warn(
      `  ! ${route}: the published cohort (${expected}) has already finished. ` +
        `Set the next cohort's dates in the admin dashboard and redeploy.`,
    );
  } else {
    console.log(
      `  ✓ ${route} schedule matches the live course ` +
        `(${required.length === 1 ? expected : `${required.length} days from ${expected}`})`,
    );
  }
}

if (failures > 0) {
  console.error(`Prerender failed for ${failures} route(s).`);
  process.exit(1);
}
