// Cloudflare Worker: a HalalLens maintenance page when the origin itself is
// unreachable (Caddy, cloudflared or the VM down), the one case the front
// Caddy's own maintenance page (caddy/maintenance.html) cannot cover.
//
// Routes (see README_ops): <domain>/* on this Worker with "Fail open", and
// <domain>/api/* on no Worker, so API calls and webhooks never pass through it.
// Fail open: if the Worker errors or the free plan's daily request limit is
// reached, traffic goes straight to the origin as if the Worker did not exist.
//
// The page is a copy of caddy/maintenance.html (wording adjusted): a Worker
// pasted into the dashboard cannot import files. Keep the two in step.

// Cloudflare answers these itself when it cannot reach or use the origin
// (530 = error 1033, tunnel down). The front Caddy never sends 502.
const ORIGIN_DOWN = new Set([502, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530]);

const PAGE = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <meta http-equiv="refresh" content="30">
  <title>HalalLens · Updating</title>
  <style>
    :root { color-scheme: dark; }
    body {
      margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      color: #e2e8f0;
      background:
        radial-gradient(1200px circle at 10% -10%, rgba(14,116,144,.35), transparent 45%),
        radial-gradient(900px circle at 85% 0%, rgba(16,185,129,.18), transparent 40%),
        #05070d;
    }
    main {
      max-width: 34rem; text-align: center; padding: 2.5rem 2rem; border-radius: 1.5rem;
      border: 1px solid rgba(255,255,255,.1); background: rgba(255,255,255,.05);
      box-shadow: 0 25px 80px rgba(3,7,18,.5);
    }
    .eyebrow { font-size: .75rem; letter-spacing: .2em; text-transform: uppercase; color: rgba(103,232,249,.8); }
    h1 { margin: 1rem 0 .75rem; font-size: 1.875rem; color: #fff; }
    p { margin: 0; line-height: 1.6; color: #cbd5e1; text-align: justify; hyphens: auto; }
    .pulse { display: inline-block; width: .6rem; height: .6rem; margin-right: .5rem; border-radius: 50%; background: #22d3ee; animation: pulse 1.6s ease-in-out infinite; }
    .note { margin-top: 1.5rem; font-size: .875rem; color: #94a3b8; text-align: center; }
    @keyframes pulse { 50% { opacity: .25; } }
    @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  </style>
</head>
<body>
  <main>
    <div class="eyebrow">HalalLens</div>
    <h1>We'll be right back</h1>
    <p>HalalLens is briefly unreachable, usually for maintenance or a restart. Your account, watchlists and screening history are safe; nothing needs to be done on your side.</p>
    <p class="note"><span class="pulse" aria-hidden="true"></span>This page reloads by itself every 30 seconds.</p>
  </main>
</body>
</html>
`;

export default {
  async fetch(request) {
    try {
      const response = await fetch(request);
      if (!ORIGIN_DOWN.has(response.status)) return response;
    } catch {
      // Network failure reaching the origin: same page.
    }
    return new Response(PAGE, {
      status: 503,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
        "retry-after": "30",
      },
    });
  },
};
