// POST /app/ip-lookup — relay for the admin Student Activity page's IP
// lookups (backend/app/ip_intel.py).
//
// ipapi.is refuses TCP connections from the Render web service's shared
// outbound address (another tenant got it firewalled), so the API asks from
// Cloudflare's edge instead. Body: { ips: [up to 100 addresses], key }.
// The caller must bring its own ipapi.is key — without one this relays
// nothing, so it is never a free lookup service for anyone else — and the
// answer is passed back unchanged. Nothing is stored or logged here.
const UPSTREAM = 'https://api.ipapi.is';

export async function onRequestPost({ request }) {
  let body;
  try {
    body = JSON.parse((await request.text()).slice(0, 16384));
  } catch (e) {
    return json({ error: 'bad json' }, 400);
  }
  const key = typeof body?.key === 'string' ? body.key.trim() : '';
  const ips = Array.isArray(body?.ips) ? body.ips : null;
  if (!key || key.length > 128 || !ips || ips.length === 0 || ips.length > 100 ||
      !ips.every((ip) => typeof ip === 'string' && ip.length <= 64)) {
    return json({ error: 'expected { ips: [1-100 addresses], key }' }, 400);
  }
  const init = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ips, key }),
  };
  if (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
    init.signal = AbortSignal.timeout(8000);
  }
  try {
    const res = await fetch(UPSTREAM, init);
    return new Response(await res.text(), {
      status: res.status,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    });
  } catch (e) {
    return json({ error: 'upstream unreachable' }, 502);
  }
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
