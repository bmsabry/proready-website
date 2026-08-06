/**
 * GET /download/<slug> — counted download of any registered software product.
 *
 * Replaces the per-product function (pro3dworks.js). The software registry
 * (GET {API_BASE}/api/products/software) decides which slugs exist and which
 * static asset each serves ({slug, asset_path}); the response is cached at
 * the edge for 5 minutes so downloads don't wait on (or hammer) the API.
 * Shipping a new product is an admin action, not a deploy.
 *
 * Contract, unchanged from the original pro3dworks function:
 *   - serve via the ASSETS binding as a forced application/octet-stream
 *     attachment with Cache-Control: no-store
 *   - log one row (edge geo, referrer, UA — never the IP) fire-and-forget to
 *     POST /api/track/download in waitUntil(); the download must NEVER break
 *     because logging failed
 *   - on any serve error, fail open with a 302 to the raw asset path
 *
 * /download/pro3dworks keeps working even when the API is down or cold: the
 * compiled-in fallback map below answers whenever the registry can't.
 */
const API_BASE = 'https://proreadyengineer-training-api-jd9a.onrender.com';
const REGISTRY_URL = `${API_BASE}/api/products/software`;
const REGISTRY_TTL_SECONDS = 300;
// Render free tier cold-starts in 30-60 s; don't make a visitor's download
// wait on that. The aborted request still wakes the server for the retry.
const REGISTRY_TIMEOUT_MS = 6000;

// Safety net for API downtime. Registry entries win whenever it's reachable.
const STATIC_ASSET_PATHS = {
  pro3dworks: '/downloads/Pro3DWorks.html',
};

async function lookupAssetPath(slug, waitUntil) {
  const cache = caches.default;
  let res = await cache.match(REGISTRY_URL);
  if (!res) {
    const init = { headers: { Accept: 'application/json' } };
    if (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
      init.signal = AbortSignal.timeout(REGISTRY_TIMEOUT_MS);
    }
    const upstream = await fetch(REGISTRY_URL, init);
    if (!upstream.ok) throw new Error('registry ' + upstream.status);
    res = new Response(upstream.body, upstream);
    res.headers.set('Cache-Control', `public, max-age=${REGISTRY_TTL_SECONDS}`);
    waitUntil(cache.put(REGISTRY_URL, res.clone()));
  }
  const products = await res.json();
  const product = Array.isArray(products)
    ? products.find((p) => p && p.slug === slug)
    : null;
  return product && product.asset_path ? String(product.asset_path) : null;
}

export async function onRequestGet(context) {
  const { request, env, params, waitUntil } = context;
  const cf = request.cf || {};

  // [[slug]] is a catch-all: params.slug is the list of path segments after
  // /download/. Exactly one segment names a product; anything else is a 404.
  const parts = Array.isArray(params.slug) ? params.slug : [params.slug];
  const slug = String(parts[0] || '').trim().toLowerCase();
  if (!slug || parts.length > 1) return new Response('Not found', { status: 404 });

  let assetPath = null;
  try {
    assetPath = await lookupAssetPath(slug, waitUntil);
  } catch (e) {
    assetPath = null; // registry unreachable — fall through to the static map
  }
  if (!assetPath) assetPath = STATIC_ASSET_PATHS[slug] || null;
  if (!assetPath) return new Response('Not found', { status: 404 });

  waitUntil(
    fetch(`${API_BASE}/api/track/download`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product: slug,
        country: cf.country || '',
        region: cf.region || '',
        city: cf.city || '',
        timezone: cf.timezone || '',
        colo: cf.colo || '',
        referrer: request.headers.get('Referer') || '',
        user_agent: request.headers.get('User-Agent') || '',
      }),
    }).catch(() => {})
  );

  const assetUrl = new URL(assetPath, request.url);
  const filename = (assetPath.split('/').pop() || `${slug}.bin`).replace(/"/g, '');
  try {
    const asset = await env.ASSETS.fetch(new Request(assetUrl, { method: 'GET' }));
    if (!asset.ok) throw new Error('asset ' + asset.status);
    const headers = new Headers(asset.headers);
    headers.set('Content-Disposition', `attachment; filename="${filename}"`);
    // Serve as a binary attachment: Cloudflare HTML transforms (email
    // obfuscation, Rocket Loader) rewrite text/html bodies and would break
    // the app's mailto links in the downloaded copy. Octet-stream bodies
    // pass through byte-exact; the filename keeps the real extension.
    headers.set('Content-Type', 'application/octet-stream');
    // Every download must reach this function so it gets counted.
    headers.set('Cache-Control', 'no-store');
    return new Response(asset.body, { status: 200, headers });
  } catch (e) {
    // Fail-open: uncounted is better than broken.
    return Response.redirect(assetUrl.toString(), 302);
  }
}
