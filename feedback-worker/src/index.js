// bouldervotes-feedback: keeps the daily page counts for bouldervotes.org.
// It also took feedback until 2026-10-31; that is closed (410, nothing stored).
// The admin endpoints still read and delete the notes already in D1.

const STATUSES = ["new", "reviewed", "fixed", "declined"];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...extra },
  });
}

const str = (v) => (v === undefined || v === null ? "" : String(v)).trim();

// The form and the agent endpoint are closed. The body is never read.
const closed = () => json({ ok: false, error: "closed", message: "Feedback is closed." }, 410, CORS);

// Admin: read rows, set status, delete. Bearer ADMIN_TOKEN.
function authorized(request, env) {
  const h = request.headers.get("Authorization") || "";
  const token = h.startsWith("Bearer ") ? h.slice(7) : "";
  if (!env.ADMIN_TOKEN || !token || token.length !== env.ADMIN_TOKEN.length) return false;
  let diff = 0;
  for (let i = 0; i < token.length; i++) diff |= token.charCodeAt(i) ^ env.ADMIN_TOKEN.charCodeAt(i);
  return diff === 0;
}

async function handleAdmin(request, env, url) {
  if (!authorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401, { "WWW-Authenticate": "Bearer" });
  const m = url.pathname.match(/^\/admin\/feedback\/(\d+)$/);
  if (m) {
    const id = Number(m[1]);
    if (request.method === "DELETE") {
      const r = await env.DB.prepare("DELETE FROM feedback WHERE id = ?").bind(id).run();
      return json({ ok: r.meta.changes === 1, id, deleted: r.meta.changes });
    }
    if (request.method === "POST" || request.method === "PATCH") {
      let body;
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      const status = str(body.status);
      if (!STATUSES.includes(status)) return json({ ok: false, error: "status" }, 400);
      const r = await env.DB.prepare("UPDATE feedback SET status = ? WHERE id = ?").bind(status, id).run();
      return json({ ok: r.meta.changes === 1, id, status });
    }
    return json({ ok: false, error: "method" }, 405);
  }
  if (url.pathname !== "/admin/feedback" || request.method !== "GET") return json({ ok: false, error: "not_found" }, 404);
  const status = url.searchParams.get("status") || "new";
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 100, 1), 500);
  const stmt = status === "all"
    ? env.DB.prepare("SELECT * FROM feedback ORDER BY id DESC LIMIT ?").bind(limit)
    : STATUSES.includes(status)
      ? env.DB.prepare("SELECT * FROM feedback WHERE status = ? ORDER BY id DESC LIMIT ?").bind(status, limit)
      : null;
  if (!stmt) return json({ ok: false, error: "status" }, 400);
  const { results } = await stmt.all();
  return json({ ok: true, status, count: results.length, rows: results });
}

// Page counts. Each page on the site sends {"path": "/its/own/path.html"} once per load.
// We keep one number per (UTC day, path) and nothing about the visitor.
const COUNT = {
  body_max_bytes: 512,
  path_max: 200,
  per_row_per_day: 50000, // one page can't be pushed past this in a day
  paths_per_day: 2000, // nor can a script add endless made-up paths
};
const COUNT_PATH = /^\/(?:[a-z0-9_.-]+\/)*(?:[a-z0-9_.-]+\.html)?$/;

function countCors(env) {
  return {
    "Access-Control-Allow-Origin": env.SITE_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

// Reads at most `max` bytes; cancels the stream and returns null past that.
async function readCapped(request, max) {
  if (Number(request.headers.get("Content-Length") || 0) > max) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) {
    all.set(c, at);
    at += c.byteLength;
  }
  return new TextDecoder().decode(all);
}

async function handleCount(request, env) {
  if (request.headers.get("Origin") !== env.SITE_ORIGIN) return new Response(null, { status: 403 });
  const cors = countCors(env);
  const text = await readCapped(request, COUNT.body_max_bytes);
  if (text === null) return new Response(null, { status: 413, headers: cors });
  let path;
  try {
    path = JSON.parse(text)?.path;
  } catch {}
  if (typeof path !== "string" || path.length > COUNT.path_max || !COUNT_PATH.test(path) || path.includes("..")) {
    return new Response(null, { status: 400, headers: cors });
  }
  const day = new Date().toISOString().slice(0, 10);
  // New paths only while the day has room; known paths only up to the per-row cap.
  await env.DB.prepare(
    `INSERT INTO page_counts (day, path, n)
       SELECT ?1, ?2, 1
       WHERE EXISTS (SELECT 1 FROM page_counts WHERE day = ?1 AND path = ?2)
          OR (SELECT COUNT(*) FROM page_counts WHERE day = ?1) < ?3
     ON CONFLICT (day, path) DO UPDATE SET n = n + 1 WHERE n < ?4`
  )
    .bind(day, path, COUNT.paths_per_day, COUNT.per_row_per_day)
    .run();
  return new Response(null, { status: 204, headers: cors });
}

// Admin: aggregate rows for the last N days (default 30, at most 366).
async function handleCounts(request, env, url) {
  if (!authorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401, { "WWW-Authenticate": "Bearer" });
  const asked = Math.floor(Number(url.searchParams.get("days") ?? 30));
  const days = Math.min(Math.max(Number.isFinite(asked) ? asked : 30, 1), 366);
  const since = new Date(Date.now() - (days - 1) * 86400e3).toISOString().slice(0, 10);
  const { results } = await env.DB.prepare(
    "SELECT day, path, n FROM page_counts WHERE day >= ? ORDER BY day DESC, n DESC, path"
  )
    .bind(since)
    .all();
  return json({ ok: true, days, since, rows: results });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const method = request.method;

    if (path === "/api/v1/count") {
      if (method === "POST") return handleCount(request, env);
      if (method === "OPTIONS") return new Response(null, { status: 204, headers: countCors(env) });
      return new Response(null, { status: 405, headers: { Allow: "POST, OPTIONS" } });
    }
    if (path === "/api/v1/counts" && method === "GET") return handleCounts(request, env, url);

    if (path.startsWith("/api/") && method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    if (path === "/api/v1/feedback" || path === "/api/v1/feedback/schema" || path === "/") return closed();

    if (path.startsWith("/admin/feedback")) return handleAdmin(request, env, url);

    return json({ ok: false, error: "not_found" }, 404);
  },
};
