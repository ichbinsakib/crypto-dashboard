// Password gate for the whole site (Cloudflare Pages Function). Fails closed: with no SITE_PASSWORD secret nothing is served.
const COOKIE = "kairo_auth";
const MAX_AGE = 60 * 60 * 24 * 30;
const enc = new TextEncoder();

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, "0")).join("");
}
function safeEq(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
async function makeToken(pw, exp) { return exp + "." + await hmac(pw, "kairo-session:" + exp); }
async function validToken(pw, tok) {
  const [exp, sig] = (tok || "").split(".");
  if (!exp || !sig || !(Number(exp) > Date.now() / 1000)) return false;
  return safeEq(sig, await hmac(pw, "kairo-session:" + exp));
}
function getCookie(req, name) {
  for (const p of (req.headers.get("Cookie") || "").split(";")) {
    const [k, ...v] = p.trim().split("=");
    if (k === name) return v.join("=");
  }
  return "";
}
function page(msg, status = 200) {
  const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Kairo — sign in</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0f17;color:#e6e9ef;font-family:system-ui,sans-serif}
form{width:min(320px,88vw);display:grid;gap:12px}h1{font-size:20px;margin:0 0 4px}
input,button{font:inherit;padding:12px;border-radius:8px;border:1px solid #2a3344;background:#121826;color:inherit}
button{background:#3b82f6;border-color:#3b82f6;font-weight:600;cursor:pointer}.e{color:#f87171;font-size:14px;min-height:18px}</style></head>
<body><form method="post" action="/__login"><h1>Kairo</h1>
<input type="password" name="password" placeholder="Password" autocomplete="current-password" autofocus required>
<button type="submit">Sign in</button><div class="e">${msg}</div></form></body></html>`;
  return new Response(html, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex" } });
}

export async function onRequest({ request, env, next }) {
  const pw = env.SITE_PASSWORD;
  if (!pw) return new Response("Site not configured.", { status: 503, headers: { "Cache-Control": "no-store" } });
  const url = new URL(request.url);

  if (url.pathname === "/__login" && request.method === "POST") {
    const form = await request.formData().catch(() => null);
    const given = String((form && form.get("password")) || "");
    const ok = safeEq(await hmac(pw, "login:" + given), await hmac(pw, "login:" + pw));
    if (!ok) { await new Promise(r => setTimeout(r, 1000)); return page("Wrong password.", 401); }
    const exp = Math.floor(Date.now() / 1000) + MAX_AGE;
    return new Response(null, { status: 303, headers: {
      Location: "/", "Cache-Control": "no-store",
      "Set-Cookie": `${COOKIE}=${await makeToken(pw, exp)}; Max-Age=${MAX_AGE}; Path=/; HttpOnly; Secure; SameSite=Strict`,
    } });
  }
  if (await validToken(pw, getCookie(request, COOKIE))) {
    const res = await next();
    const out = new Response(res.body, res);
    out.headers.set("Cache-Control", "private, no-store");
    return out;
  }
  return page("", 401);
}
