// GET /app/version?product=pro3dworks&v=v2.53.1
//
// The in-app "check for updates" endpoint. Returns the latest published
// version (from /pro3dworks-version.json in this deployment) and logs an
// anonymous launch event — country/region/city and app version only, same
// privacy policy as download tracking: no IP addresses are ever stored.
// CORS is open because the app runs from file:// (origin "null").
const API_BASE = 'https://proreadyengineer-training-api-jd9a.onrender.com';

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const product = (url.searchParams.get('product') || 'pro3dworks').slice(0, 40);
  const appVersion = (url.searchParams.get('v') || '').slice(0, 20);
  const cf = request.cf || {};
  context.waitUntil(fetch(`${API_BASE}/api/track/launch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      product,
      version: appVersion,
      country: cf.country || null,
      region: cf.region || null,
      city: cf.city || null,
    }),
  }).catch(() => {}));

  let info = null;
  try {
    const res = await env.ASSETS.fetch(new URL('/pro3dworks-version.json', url.origin));
    if (res.ok) info = await res.json();
  } catch (e) { /* asset missing — reply gracefully */ }

  return new Response(JSON.stringify(info || { latest: null }), {
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store',
    },
  });
}
