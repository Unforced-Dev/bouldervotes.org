// bouldervotes-feedback: collects corrections and suggestions for bouldervotes.org.
// Stores submissions in D1. Never renders them publicly. No CAPTCHA: honeypot,
// rate limits, size limits and a links-vs-words check instead.

const KINDS = ["correction", "suggestion", "other"];
const SUBMITTERS = ["person", "ai-agent"];
const STATUSES = ["new", "reviewed", "fixed", "declined"];
const LIMITS = {
  message_min: 10,
  message_max: 4000,
  contact_max: 200,
  page_url_max: 500,
  source_url_max: 1000,
  agent_name_max: 100,
  user_agent_max: 300,
  body_max_bytes: 20000,
  per_ip_per_hour: 5,
  global_per_day: 200,
};
const HONEYPOT = "homepage"; // hidden in the HTML form; people and agents leave it empty

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

class Reject extends Error {
  constructor(reason, status = 400) {
    super(reason);
    this.reason = reason;
    this.status = status;
  }
}

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...extra },
  });
}

function redirect(url) {
  return new Response(null, { status: 303, headers: { Location: url, "Cache-Control": "no-store" } });
}

const str = (v) => (v === undefined || v === null ? "" : String(v)).trim();

function truthy(v) {
  if (typeof v === "boolean") return v;
  return ["1", "true", "yes", "on"].includes(str(v).toLowerCase());
}

function isHttpUrl(s) {
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Returns a clean row or throws Reject(reason).
function validate(input) {
  if (str(input[HONEYPOT])) throw new Reject("rejected");

  const kind = str(input.kind).toLowerCase() || "other";
  if (!KINDS.includes(kind)) throw new Reject("kind");

  const message = str(input.message);
  if (message.length < LIMITS.message_min) throw new Reject("message_too_short");
  if (message.length > LIMITS.message_max) throw new Reject("message_too_long");

  const links = (message.match(/(https?:\/\/|www\.)\S+/gi) || []).length;
  const words = message
    .replace(/(https?:\/\/|www\.)\S+/gi, " ")
    .split(/\s+/)
    .filter((w) => /[a-z0-9]/i.test(w)).length;
  if (links > words) throw new Reject("too_many_links");

  const contact = str(input.contact);
  if (contact.length > LIMITS.contact_max) throw new Reject("contact_too_long");

  const page_url = str(input.page_url ?? input.page);
  if (page_url.length > LIMITS.page_url_max) throw new Reject("page_url_too_long");

  let source_url = str(input.source_url);
  if (source_url && !/^[a-z][a-z0-9+.-]*:/i.test(source_url) && /^[\w-]+(\.[\w-]+)+(\/|$)/.test(source_url)) {
    source_url = "https://" + source_url; // people often paste "example.org/page"
  }
  if (source_url.length > LIMITS.source_url_max) throw new Reject("source_url_too_long");
  if (source_url && !isHttpUrl(source_url)) throw new Reject("source_url_invalid");

  const submitter_type = str(input.submitter_type).toLowerCase() || "person";
  if (!SUBMITTERS.includes(submitter_type)) throw new Reject("submitter_type");

  const agent_name = str(input.agent_name);
  if (agent_name.length > LIMITS.agent_name_max) throw new Reject("agent_name_too_long");

  const on_behalf_of_user = submitter_type === "ai-agent" && truthy(input.on_behalf_of_user) ? 1 : 0;

  return {
    kind,
    page_url: page_url || null,
    message,
    contact: contact || null,
    submitter_type,
    agent_name: submitter_type === "ai-agent" ? agent_name || null : null,
    on_behalf_of_user,
    source_url: source_url || null,
  };
}

async function store(request, env, row) {
  if (!env.SALT) throw new Reject("server_not_configured", 500);
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const ip_hash = await sha256Hex(ip + env.SALT);
  const now = new Date();
  const hourAgo = new Date(now.getTime() - 3600e3).toISOString();
  const dayAgo = new Date(now.getTime() - 86400e3).toISOString();

  const [perIp, global] = await env.DB.batch([
    env.DB.prepare("SELECT COUNT(*) AS n FROM feedback WHERE ip_hash = ? AND created_at > ?").bind(ip_hash, hourAgo),
    env.DB.prepare("SELECT COUNT(*) AS n FROM feedback WHERE created_at > ?").bind(dayAgo),
  ]);
  if (perIp.results[0].n >= LIMITS.per_ip_per_hour) throw new Reject("rate_limited", 429);
  if (global.results[0].n >= LIMITS.global_per_day) throw new Reject("busy", 429);

  const ua = (request.headers.get("User-Agent") || "").slice(0, LIMITS.user_agent_max);
  const res = await env.DB.prepare(
    `INSERT INTO feedback (created_at, kind, page_url, message, contact, submitter_type, agent_name,
       on_behalf_of_user, source_url, user_agent, ip_hash, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')`
  )
    .bind(now.toISOString(), row.kind, row.page_url, row.message, row.contact, row.submitter_type,
      row.agent_name, row.on_behalf_of_user, row.source_url, ua || null, ip_hash)
    .run();
  return res.meta.last_row_id;
}

function tooBig(request) {
  const len = Number(request.headers.get("Content-Length") || 0);
  return len > LIMITS.body_max_bytes;
}

// 1. HTML form, no JavaScript needed. Always answers with a 303.
async function handleForm(request, env) {
  const back = `${env.SITE_ORIGIN}/feedback.html`;
  let page = "";
  try {
    if (tooBig(request)) throw new Reject("too_large");
    const form = await request.formData();
    const input = Object.fromEntries([...form.entries()].map(([k, v]) => [k, typeof v === "string" ? v : ""]));
    if (!str(input.page)) {
      // Without JavaScript the form can't prefill "which page"; the footer link's ?page= is still in the Referer.
      try {
        const ref = new URL(request.headers.get("Referer") || "");
        if (ref.origin === env.SITE_ORIGIN) input.page = ref.searchParams.get("page") || "";
      } catch {}
    }
    page = str(input.page).slice(0, LIMITS.page_url_max);
    input.submitter_type = "person"; // the web form is for people; agents use the JSON endpoint
    await store(request, env, validate(input));
    return redirect(`${back}?sent=1#sent`);
  } catch (e) {
    const reason = e instanceof Reject ? e.reason : "server_error";
    if (!(e instanceof Reject)) console.error(e);
    const q = new URLSearchParams({ error: reason });
    if (page) q.set("page", page);
    return redirect(`${back}?${q}#problem`);
  }
}

// 2. JSON for AI agents and scripts.
async function handleJson(request, env) {
  try {
    if (tooBig(request)) throw new Reject("too_large", 413);
    let input;
    try {
      input = await request.json();
    } catch {
      throw new Reject("invalid_json");
    }
    if (!input || typeof input !== "object" || Array.isArray(input)) throw new Reject("invalid_json");
    const id = await store(request, env, validate(input));
    return json({ ok: true, id, status: "new", note: "Thank you. A person reads every note. Corrections are checked against sources before anything changes." }, 201, CORS);
  } catch (e) {
    const reason = e instanceof Reject ? e.reason : "server_error";
    const status = e instanceof Reject ? e.status : 500;
    if (!(e instanceof Reject)) console.error(e);
    return json({ ok: false, error: reason }, status, CORS);
  }
}

// 3. Field description.
function schema(env, origin) {
  return {
    name: "Boulder Votes feedback",
    description:
      "Send a correction, suggestion or other note about bouldervotes.org, a nonpartisan guide to the City of Boulder election on Nov. 3, 2026. " +
      "A person reads every note. Corrections are checked against sources before anything changes. Notes are never published.",
    endpoint: `${origin}/api/v1/feedback`,
    method: "POST",
    content_type: "application/json",
    returns: { ok: "boolean", id: "integer, when ok", error: "string, when not ok" },
    guidance_for_ai_assistants: [
      "Only submit when the user asks you to, or when you find a factual error on the site and can cite a source.",
      "Set submitter_type to 'ai-agent' and agent_name to your name (e.g. 'ChatGPT', 'Claude').",
      "Set on_behalf_of_user to true when you are relaying the user's own report.",
      "For corrections, include source_url: a link to the document that shows the correct fact.",
      "Do not include the user's personal details unless they ask you to pass on a way to reach them.",
    ],
    fields: {
      kind: { type: "string", enum: KINDS, required: true },
      message: { type: "string", required: true, min_length: LIMITS.message_min, max_length: LIMITS.message_max, note: "Plain text. Links may not outnumber words." },
      page_url: { type: "string", required: false, max_length: LIMITS.page_url_max, note: "The bouldervotes.org page this is about, e.g. /mayor.html or a full URL." },
      source_url: { type: "string (http or https URL)", required: false, max_length: LIMITS.source_url_max, note: "Evidence link. Strongly encouraged for corrections." },
      contact: { type: "string", required: false, max_length: LIMITS.contact_max, note: "Optional email or name. We can only reply if this is given." },
      submitter_type: { type: "string", enum: SUBMITTERS, default: "person" },
      agent_name: { type: "string", required: false, max_length: LIMITS.agent_name_max, note: "For ai-agent submissions." },
      on_behalf_of_user: { type: "boolean", default: false, note: "For ai-agent submissions: true when relaying a user's report." },
    },
    limits: {
      per_client_per_hour: LIMITS.per_ip_per_hour,
      total_per_day: LIMITS.global_per_day,
      max_body_bytes: LIMITS.body_max_bytes,
    },
    errors: ["kind", "message_too_short", "message_too_long", "too_many_links", "contact_too_long", "page_url_too_long",
      "source_url_invalid", "source_url_too_long", "submitter_type", "agent_name_too_long", "invalid_json",
      "too_large", "rate_limited", "busy", "rejected"],
    example: {
      kind: "correction",
      page_url: "https://bouldervotes.org/2026.html",
      message: "(Example only.) The page gives one date for X, but the linked source gives a different date.",
      source_url: "https://example.org/the-source-document",
      submitter_type: "ai-agent",
      agent_name: "Claude",
      on_behalf_of_user: true,
    },
  };
}

// 4. Admin: read rows, set status, delete. Bearer ADMIN_TOKEN.
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const method = request.method;

    if (path.startsWith("/api/") && method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    if (path === "/api/v1/feedback/schema" && method === "GET") return json(schema(env, url.origin), 200, CORS);
    if (path === "/api/v1/feedback" && method === "POST") return handleJson(request, env);
    if (path === "/api/v1/feedback") return json({ ok: false, error: "use POST; see /api/v1/feedback/schema" }, 405, CORS);

    if (path.startsWith("/admin/feedback")) return handleAdmin(request, env, url);

    if (path === "/" && method === "POST") return handleForm(request, env);
    if (path === "/" && method === "GET") return redirect(`${env.SITE_ORIGIN}/feedback.html`);

    return json({ ok: false, error: "not_found" }, 404);
  },
};
