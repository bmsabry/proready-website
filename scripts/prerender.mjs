/**
 * Build-time prerenderer.
 * Runs after `vite build` (client) + `vite build --ssr` (server bundle).
 * Renders every public route to static HTML with per-page head tags and
 * JSON-LD baked in, writes dist/spa.html as the client-render fallback
 * shell (admin + unknown routes), and generates dist/sitemap.xml.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const ORIGIN = 'https://proreadyengineer.com';
const { render, PRERENDER_ROUTES } = await import('../dist-ssr/entry-server.js');

const template = readFileSync('dist/index.html', 'utf8');

// Pristine SPA shell for non-prerendered routes (admin, 404 fallback).
writeFileSync('dist/spa.html', template);

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
    out = out.replace('<div id="root"></div>', () => `<div id="root">${appHtml}</div>`);

    const file = route.path === '/' ? 'dist/index.html' : join('dist', route.path, 'index.html');
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

if (failures > 0) {
  console.error(`Prerender failed for ${failures} route(s).`);
  process.exit(1);
}
