// POST /app/ping — anonymous, OPT-IN usage ping from Pro3DWorks.
//
// The app sends this beacon only when its user has explicitly enabled the
// usage ping in the Privacy & data dialog. The body is counts only:
// { product, version, minutes, features: { bom: 2, photoreal: 1, ... } }.
// This function adds city-level geography from the edge (request.cf) and
// forwards to the stats backend. Same privacy policy as everything else:
// no IP addresses are ever stored, no identifiers of any kind.
//
// sendBeacon posts text/plain (keeps the request preflight-free from the
// app's file:// origin), so the JSON is parsed from the raw body text.
const API_BASE = 'https://proreadyengineer-training-api-jd9a.onrender.com';

export async function onRequestPost(context) {
  const { request } = context;
  let body = null;
  try {
    const text = (await request.text()).slice(0, 4096);
    body = JSON.parse(text);
  } catch (e) { /* malformed — ignored below */ }

  if (body && typeof body === 'object' && typeof body.product === 'string') {
    const features = {};
    if (body.features && typeof body.features === 'object') {
      for (const [k, v] of Object.entries(body.features).slice(0, 24)) {
        if (Number.isInteger(v) && v >= 0 && v <= 1000000) features[String(k).slice(0, 32)] = v;
      }
    }
    const cf = request.cf || {};
    context.waitUntil(fetch(`${API_BASE}/api/track/usage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product: String(body.product).slice(0, 40),
        version: typeof body.version === 'string' ? body.version.slice(0, 20) : null,
        minutes: Number.isInteger(body.minutes) && body.minutes >= 0 ? Math.min(body.minutes, 100000) : null,
        features: Object.keys(features).length ? features : null,
        country: cf.country || null,
        region: cf.region || null,
        city: cf.city || null,
      }),
    }).catch(() => {}));
  }

  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store',
    },
  });
}

// Preflight safety net (sendBeacon with text/plain never needs it, but a
// fetch() fallback from some browser might).
export async function onRequestOptions() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '86400',
    },
  });
}
