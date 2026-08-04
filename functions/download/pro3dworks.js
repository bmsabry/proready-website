/**
 * GET /download/pro3dworks — counted download of Pro3DWorks.
 *
 * Serves the static file at /downloads/Pro3DWorks.html via the ASSETS binding
 * and logs one row (time, edge geo, referrer, user agent — never the IP) to
 * the training API's Postgres through POST /api/track/download.
 *
 * Contract: the download must NEVER break because logging failed — the log
 * call runs in waitUntil() and all failures are swallowed.
 */
const API_BASE = 'https://proreadyengineer-training-api-jd9a.onrender.com';
const ASSET_PATH = '/downloads/Pro3DWorks.html';

export async function onRequestGet(context) {
  const { request, env, waitUntil } = context;
  const cf = request.cf || {};

  waitUntil(
    fetch(`${API_BASE}/api/track/download`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product: 'pro3dworks',
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

  const assetUrl = new URL(ASSET_PATH, request.url);
  try {
    const asset = await env.ASSETS.fetch(new Request(assetUrl, { method: 'GET' }));
    if (!asset.ok) throw new Error('asset ' + asset.status);
    const headers = new Headers(asset.headers);
    headers.set('Content-Disposition', 'attachment; filename="Pro3DWorks.html"');
    // Every download must reach this function so it gets counted.
    headers.set('Cache-Control', 'no-store');
    return new Response(asset.body, { status: 200, headers });
  } catch (e) {
    // Fail-open: uncounted is better than broken.
    return Response.redirect(assetUrl.toString(), 302);
  }
}
