// End-to-end: headless Chromium opens the built site as https://bouldervotes.org, and each page's
// count snippet calls the real Worker running in local workerd as https://feedback.bouldervotes.org.
// Nothing touches production. Needs chromium and openssl on PATH; run from feedback-worker/:
//   node e2e/browser.mjs [screenshot-dir]
import { Miniflare, supportedCompatibilityDate } from "miniflare";
import https from "node:https";
import { execFile, execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);
const worker = new URL("..", import.meta.url).pathname;
const docs = new URL("../../docs", import.meta.url).pathname;
const shots = resolve(process.argv[2] || mkdtempSync(join(tmpdir(), "bv-shots-")));
mkdirSync(shots, { recursive: true });
const tls = mkdtempSync(join(tmpdir(), "bv-tls-"));
execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=bouldervotes.org",
  "-keyout", join(tls, "key.pem"), "-out", join(tls, "cert.pem")], { stdio: "ignore" });

const mf = new Miniflare({
  modules: true, scriptPath: "src/index.js", rootPath: worker, compatibilityDate: supportedCompatibilityDate,
  d1Databases: { DB: "e2e" }, bindings: { SITE_ORIGIN: "https://bouldervotes.org" }, https: true, port: 0,
});
const workerUrl = await mf.ready;
const db = await mf.getD1Database("DB");
for (const s of readFileSync(join(worker, "schema.sql"), "utf8").replace(/--.*$/gm, "").split(";").map((x) => x.trim()).filter(Boolean)) {
  await db.prepare(s).run();
}

const types = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml",
  ".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2" };
const site = https.createServer({ key: readFileSync(join(tls, "key.pem")), cert: readFileSync(join(tls, "cert.pem")) }, (req, res) => {
  let p = decodeURIComponent(new URL(req.url, "https://x").pathname);
  if (p.endsWith("/")) p += "index.html";
  const f = join(docs, p);
  if (!f.startsWith(docs) || !existsSync(f)) return res.writeHead(404).end();
  res.writeHead(200, { "Content-Type": types[p.slice(p.lastIndexOf("."))] || "application/octet-stream" }).end(readFileSync(f));
}).listen(0);
await new Promise((r) => site.on("listening", r));

const rules = `MAP bouldervotes.org 127.0.0.1:${site.address().port}, MAP feedback.bouldervotes.org ${workerUrl.host}`;
const open = (path, out) => run("chromium", ["--headless=new", "--no-sandbox", "--disable-gpu", "--ignore-certificate-errors",
  `--host-resolver-rules=${rules}`, "--virtual-time-budget=4000", "--window-size=1200,1750", `--screenshot=${join(shots, out)}`,
  `https://bouldervotes.org${path}`]);

let failed = false;
try {
  await open("/about.html", "01-about-visitor-counts.png");
  await open("/", "02-home.png");
  await open("/about.html", "03-about-again.png");
  await new Promise((r) => setTimeout(r, 500));
  const rows = (await db.prepare("SELECT path, n FROM page_counts ORDER BY path").all()).results;
  console.log("page_counts:", JSON.stringify(rows));
  const want = [{ path: "/", n: 1 }, { path: "/about.html", n: 2 }];
  failed = JSON.stringify(rows) !== JSON.stringify(want);
  console.log(failed ? `FAIL: expected ${JSON.stringify(want)}` : "OK: three page loads, three counts");
  console.log("screenshots:", shots);
} finally {
  site.close();
  await mf.dispose();
}
process.exit(failed ? 1 : 0);
