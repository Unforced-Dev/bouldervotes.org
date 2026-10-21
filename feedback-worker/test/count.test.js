// Page counts: POST /api/v1/count and GET /api/v1/counts, run in real workerd with a real local D1.
import { after, before, beforeEach, describe, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import http from "node:http";
import { Miniflare, supportedCompatibilityDate } from "miniflare";

const SITE = "https://bouldervotes.org";
const BASE = "https://feedback.bouldervotes.org";
const ADMIN = "test-admin-token-0123456789";

let mf, db;

function statements(file) {
  return readFileSync(new URL(file, import.meta.url), "utf8")
    .replace(/--.*$/gm, "")
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
}

before(async () => {
  mf = new Miniflare({
    modules: true,
    scriptPath: new URL("../src/index.js", import.meta.url).pathname,
    // wrangler.toml may name a date newer than the local workerd build knows.
    compatibilityDate: supportedCompatibilityDate,
    d1Databases: { DB: "test-db" },
    bindings: { SITE_ORIGIN: SITE, ADMIN_TOKEN: ADMIN, SALT: "test-salt" },
  });
  db = await mf.getD1Database("DB");
  for (const s of statements("../schema.sql")) await db.prepare(s).run();
});

after(() => mf.dispose());

beforeEach(async () => {
  await db.prepare("DELETE FROM page_counts").run();
});

const today = () => new Date().toISOString().slice(0, 10);

function count(body, { origin = SITE, headers = {} } = {}) {
  const h = { "Content-Type": "text/plain", ...headers };
  if (origin) h.Origin = origin;
  return mf.dispatchFetch(`${BASE}/api/v1/count`, {
    method: "POST",
    headers: h,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function rows() {
  return (await db.prepare("SELECT * FROM page_counts ORDER BY path").all()).results;
}

describe("POST /api/v1/count", () => {
  test("counts a page view: 204, no body, CORS for the site only, no credentials", async () => {
    const r = await count({ path: "/" });
    assert.equal(r.status, 204);
    assert.equal(await r.text(), "");
    assert.equal(r.headers.get("Access-Control-Allow-Origin"), SITE);
    assert.equal(r.headers.get("Access-Control-Allow-Credentials"), null);
    assert.deepEqual(await rows(), [{ day: today(), path: "/", n: 1 }]);
  });

  test("upserts: repeat views increment one row per (day, path)", async () => {
    for (let i = 0; i < 3; i++) assert.equal((await count({ path: "/about.html" })).status, 204);
    assert.equal((await count({ path: "/people/" })).status, 204);
    assert.deepEqual(await rows(), [
      { day: today(), path: "/about.html", n: 3 },
      { day: today(), path: "/people/", n: 1 },
    ]);
  });

  test("rejects a foreign or missing Origin and stores nothing", async () => {
    for (const origin of ["https://evil.example", "http://bouldervotes.org", "https://bouldervotes.org.evil.example", "null", ""]) {
      const r = await count({ path: "/" }, { origin });
      assert.equal(r.status, 403, `origin ${JSON.stringify(origin)}`);
      assert.equal(r.headers.get("Access-Control-Allow-Origin"), null);
    }
    assert.deepEqual(await rows(), []);
  });

  test("validates path shape", async () => {
    const bad = ["", "about.html", "/About.html", "/about", "/a b.html", "/x.html?q=1", "/x.html#h", "/../x.html",
      "//evil.example/", "/" + "a".repeat(196) + ".html", 42, null];
    for (const path of bad) {
      const r = await count({ path });
      assert.equal(r.status, 400, `path ${JSON.stringify(path)}`);
    }
    for (const body of ["not json", "[]", "null", "{}"]) assert.equal((await count(body)).status, 400, body);
    const ok = ["/", "/index.html", "/people/dave-martus.html", "/compare/2026-lwv-forum-q06.html", "/print/", "/" + "a".repeat(194) + ".html"];
    for (const path of ok) assert.equal((await count({ path })).status, 204, path);
    assert.equal((await rows()).length, ok.length);
  });

  test("caps the body at 512 bytes by Content-Length", async () => {
    const r = await count({ path: "/", pad: "x".repeat(600) });
    assert.equal(r.status, 413);
    assert.deepEqual(await rows(), []);
  });

  test("caps a streamed body with no Content-Length: answers mid-stream without draining it", async () => {
    // dispatchFetch buffers the whole request, so speak chunked HTTP to the runtime's socket directly.
    const url = await mf.ready;
    let sent = 0;
    let timer;
    const status = await new Promise((resolve, reject) => {
      const req = http.request(new URL("/api/v1/count", url), {
        method: "POST",
        headers: { Host: "feedback.bouldervotes.org", Origin: SITE, "Content-Type": "text/plain", "Transfer-Encoding": "chunked" },
      });
      req.on("response", (res) => {
        clearInterval(timer);
        res.resume();
        resolve(res.statusCode);
        req.destroy();
      });
      req.on("error", (e) => (e.code === "ECONNRESET" || e.code === "EPIPE" ? null : reject(e)));
      const chunk = "x".repeat(100);
      timer = setInterval(() => {
        if (sent > 1e6) {
          clearInterval(timer);
          reject(new Error("no response after 1 MB: the body is being drained"));
          req.destroy();
          return;
        }
        req.write(chunk);
        sent += chunk.length;
      }, 2);
    });
    assert.equal(status, 413);
    assert.ok(sent < 1e6, `sent ${sent} bytes before the answer`);
    assert.deepEqual(await rows(), []);
  });

  test("stops at the per-day cap for a row", async () => {
    await db.prepare("INSERT INTO page_counts (day, path, n) VALUES (?, '/', 49999)").bind(today()).run();
    assert.equal((await count({ path: "/" })).status, 204);
    assert.equal((await count({ path: "/" })).status, 204);
    assert.equal((await count({ path: "/" })).status, 204);
    assert.deepEqual(await rows(), [{ day: today(), path: "/", n: 50000 }]);
  });

  test("stops adding new paths past the per-day path cap, but keeps counting known ones", async () => {
    await db.prepare(
      `WITH RECURSIVE i(k) AS (SELECT 1 UNION ALL SELECT k + 1 FROM i WHERE k < 2000)
       INSERT INTO page_counts (day, path, n) SELECT ?, '/p' || k || '.html', 1 FROM i`
    ).bind(today()).run();
    assert.equal((await count({ path: "/new-page.html" })).status, 204);
    assert.equal((await count({ path: "/p7.html" })).status, 204);
    const r = (await db.prepare("SELECT path, n FROM page_counts WHERE path IN ('/new-page.html', '/p7.html')").all()).results;
    assert.deepEqual(r, [{ path: "/p7.html", n: 2 }]);
  });

  test("stores nothing about the visitor: only day, path, n", async () => {
    await count({ path: "/", ua: "x", ip: "1.2.3.4" }, {
      headers: { "User-Agent": "Mozilla/5.0 Test", Referer: "https://elsewhere.example/", Cookie: "id=abc", "CF-Connecting-IP": "203.0.113.9" },
    });
    const cols = (await db.prepare("PRAGMA table_info(page_counts)").all()).results.map((c) => c.name);
    assert.deepEqual(cols, ["day", "path", "n"]);
    assert.deepEqual(await rows(), [{ day: today(), path: "/", n: 1 }]);
    const fb = (await db.prepare("SELECT COUNT(*) AS n FROM feedback").all()).results[0].n;
    assert.equal(fb, 0);
  });

  test("OPTIONS answers with the site-only CORS headers; other methods are 405", async () => {
    const o = await mf.dispatchFetch(`${BASE}/api/v1/count`, { method: "OPTIONS", headers: { Origin: SITE } });
    assert.equal(o.status, 204);
    assert.equal(o.headers.get("Access-Control-Allow-Origin"), SITE);
    assert.equal(o.headers.get("Access-Control-Allow-Credentials"), null);
    const g = await mf.dispatchFetch(`${BASE}/api/v1/count`);
    assert.equal(g.status, 405);
    await g.arrayBuffer();
  });
});

describe("GET /api/v1/counts", () => {
  test("needs the admin token", async () => {
    const r = await mf.dispatchFetch(`${BASE}/api/v1/counts`);
    assert.equal(r.status, 401);
    await r.arrayBuffer();
    const w = await mf.dispatchFetch(`${BASE}/api/v1/counts`, { headers: { Authorization: "Bearer wrong-token-0123456789xx" } });
    assert.equal(w.status, 401);
    await w.arrayBuffer();
  });

  test("returns aggregate rows for the last N days", async () => {
    const old = new Date(Date.now() - 40 * 86400e3).toISOString().slice(0, 10);
    await db.batch([
      db.prepare("INSERT INTO page_counts (day, path, n) VALUES (?, '/', 5)").bind(today()),
      db.prepare("INSERT INTO page_counts (day, path, n) VALUES (?, '/about.html', 2)").bind(today()),
      db.prepare("INSERT INTO page_counts (day, path, n) VALUES (?, '/', 9)").bind(old),
    ]);
    const auth = { headers: { Authorization: `Bearer ${ADMIN}` } };
    const r = await mf.dispatchFetch(`${BASE}/api/v1/counts?days=7`, auth);
    assert.equal(r.status, 200);
    const j = await r.json();
    assert.equal(j.days, 7);
    assert.deepEqual(j.rows, [
      { day: today(), path: "/", n: 5 },
      { day: today(), path: "/about.html", n: 2 },
    ]);
    const all = await (await mf.dispatchFetch(`${BASE}/api/v1/counts?days=60`, auth)).json();
    assert.equal(all.rows.length, 3);
    for (const [q, want] of [["", 30], ["?days=0", 1], ["?days=-5", 1], ["?days=9999", 366], ["?days=abc", 30]]) {
      assert.equal((await (await mf.dispatchFetch(`${BASE}/api/v1/counts${q}`, auth)).json()).days, want, q);
    }
  });
});

describe("existing feedback endpoints still answer", () => {
  test("schema GET and feedback OPTIONS keep their open CORS", async () => {
    const s = await mf.dispatchFetch(`${BASE}/api/v1/feedback/schema`);
    assert.equal(s.status, 200);
    assert.equal(s.headers.get("Access-Control-Allow-Origin"), "*");
    await s.arrayBuffer();
    const o = await mf.dispatchFetch(`${BASE}/api/v1/feedback`, { method: "OPTIONS" });
    assert.equal(o.status, 204);
    assert.equal(o.headers.get("Access-Control-Allow-Origin"), "*");
  });
});
