/* Ask about this election. Vanilla JS, no cookies, nothing stored.
   The conversation lives only in this page; reloading clears it. */
(function () {
  "use strict";

  var MAX_TURNS = 12;
  var MAX_CHARS = 800;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Turns an https URL (already HTML-escaped) into a safe <a>. Links to
  // bouldervotes.org become relative so they stay on whatever host serves this page.
  function linkHtml(url, label) {
    var raw = url.replace(/&amp;/g, "&");
    var m = /^https:\/\/(?:www\.)?bouldervotes\.org(\/[^\s]*)?$/i.exec(raw);
    var href;
    if (m) {
      var path = (m[1] || "/").replace(/^\//, "");
      href = escapeHtml(path === "" ? "./" : path);
      return '<a href="' + href + '">' + label + "</a>";
    }
    return '<a href="' + url + '" rel="noopener noreferrer">' + label + "</a>";
  }

  function inline(escaped) {
    var held = [];
    function hold(html) { held.push(html); return "\u0000" + (held.length - 1) + "\u0000"; }
    var s = escaped.replace(/\[([^\]\n]+)\]\((https:\/\/[^\s)]+)\)/g, function (_, label, url) {
      return hold(linkHtml(url, label));
    });
    s = s.replace(/https:\/\/[^\s<>"]+[^\s<>".,;:!?)\]'&]|https:\/\/[^\s<>"]*&amp;[^\s<>"]*[^\s<>".,;:!?)\]']/g, function (url) {
      return hold(linkHtml(url, url));
    });
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>");
    return s.replace(/\u0000(\d+)\u0000/g, function (_, i) { return held[Number(i)]; });
  }

  // Minimal, safe markdown: paragraphs, bullet and numbered lists, > quotes,
  // headings (shown as bold), **bold**, *italic*, [text](https://...) and bare https links.
  function renderMarkdown(text) {
    var lines = escapeHtml(text).replace(/\r\n?/g, "\n").split("\n");
    var out = [];
    var para = [];
    var list = null;
    var quote = [];

    function flushPara() {
      if (para.length) { out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para = []; }
    }
    function flushList() {
      if (list) {
        out.push("<" + list.tag + ">" + list.items.map(function (i) { return "<li>" + inline(i) + "</li>"; }).join("") + "</" + list.tag + ">");
        list = null;
      }
    }
    function flushQuote() {
      if (quote.length) { out.push("<blockquote><p>" + quote.map(inline).join("<br>") + "</p></blockquote>"); quote = []; }
    }
    function flushAll() { flushPara(); flushList(); flushQuote(); }

    lines.forEach(function (line) {
      var m;
      if (/^\s*$/.test(line)) { flushAll(); return; }
      if ((m = /^\s*[-*•]\s+(.*)$/.exec(line))) {
        flushPara(); flushQuote();
        if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; }
        list.items.push(m[1]); return;
      }
      if ((m = /^\s*\d+[.)]\s+(.*)$/.exec(line))) {
        flushPara(); flushQuote();
        if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", items: [] }; }
        list.items.push(m[1]); return;
      }
      if ((m = /^&gt;\s?(.*)$/.exec(line))) { flushPara(); flushList(); quote.push(m[1]); return; }
      if ((m = /^#{1,6}\s+(.*)$/.exec(line))) { flushAll(); out.push("<p><strong>" + inline(m[1]) + "</strong></p>"); return; }
      flushList(); flushQuote(); para.push(line.replace(/^\s+/, ""));
    });
    flushAll();
    return out.join("");
  }

  function retryText(sec) {
    if (typeof sec !== "number" || !isFinite(sec) || sec <= 0) return "";
    if (sec < 90) return "Please try again in about " + Math.max(1, Math.round(sec)) + " seconds.";
    if (sec < 5400) return "Please try again in about " + Math.round(sec / 60) + " minutes.";
    return "Please try again in about " + Math.round(sec / 3600) + " hours.";
  }

  function init() {
    var root = document.getElementById("chat");
    if (!root) return;
    var gateway = (root.getAttribute("data-gateway") || "").replace(/\/+$/, "");
    var log = document.getElementById("chat-log");
    var form = document.getElementById("chat-form");
    var input = document.getElementById("chat-input");
    var send = document.getElementById("chat-send");
    var status = document.getElementById("chat-status");
    var restart = document.getElementById("chat-restart");
    var chips = document.getElementById("chat-chips");
    var count = document.getElementById("chat-count");
    var messages = [];
    var busy = false;

    root.hidden = false;

    function addMessage(role, html, isHtml) {
      var d = document.createElement("div");
      d.className = "msg " + role;
      var who = document.createElement("p");
      who.className = "who";
      who.textContent = role === "user" ? "You" : role === "assistant" ? "Guide" : "Notice";
      d.appendChild(who);
      var body = document.createElement("div");
      body.className = "body";
      if (isHtml) body.innerHTML = html; else body.textContent = html;
      d.appendChild(body);
      log.appendChild(d);
      d.scrollIntoView({ block: "nearest" });
      return d;
    }

    function turnsUsed() {
      return messages.filter(function (m) { return m.role === "user"; }).length;
    }

    function setBusy(on) {
      busy = on;
      send.disabled = on;
      root.setAttribute("aria-busy", on ? "true" : "false");
      status.textContent = on ? "Thinking it through with the guide…" : "";
    }

    function finishedState() {
      var done = turnsUsed() >= MAX_TURNS;
      input.disabled = done;
      send.disabled = done || busy;
      restart.hidden = turnsUsed() === 0;
      chips.hidden = turnsUsed() > 0;
      if (done) status.textContent = "That is the limit for one conversation (" + MAX_TURNS + " messages). Choose “Start over” to begin a new one.";
    }

    function reset() {
      messages = [];
      Array.prototype.slice.call(log.children, 1).forEach(function (n) { log.removeChild(n); });
      input.value = "";
      input.disabled = false;
      count.textContent = "";
      status.textContent = "";
      finishedState();
      input.focus();
    }

    function ask(question) {
      question = question.replace(/\s+/g, " ").trim();
      if (!question || busy || turnsUsed() >= MAX_TURNS) return;
      if (question.length > MAX_CHARS) { status.textContent = "Please keep your message under " + MAX_CHARS + " characters."; return; }
      messages.push({ role: "user", content: question });
      var bubble = addMessage("user", question, false);
      input.value = "";
      setBusy(true);
      finishedState();

      function fail(text, restore) {
        messages.pop();
        if (bubble && bubble.parentNode) bubble.parentNode.removeChild(bubble);
        if (restore) input.value = question;
        addMessage("notice", text, false);
        setBusy(false);
        finishedState();
      }

      var ctl = typeof AbortController === "function" ? new AbortController() : null;
      var timer = setTimeout(function () { if (ctl) ctl.abort(); }, 60000);
      fetch(gateway + "/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app: "bouldervotes", messages: messages }),
        credentials: "omit",
        referrerPolicy: "no-referrer",
        signal: ctl ? ctl.signal : undefined
      }).then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) { return { res: res, data: data }; });
      }).then(function (r) {
        clearTimeout(timer);
        var data = r.data;
        if (r.res.ok && data && data.ok && typeof data.answer === "string") {
          messages.push({ role: "assistant", content: data.answer });
          addMessage("assistant", renderMarkdown(data.answer), true);
          if (data.remaining && typeof data.remaining.day === "number" && data.remaining.day <= 5) {
            count.textContent = data.remaining.day + (data.remaining.day === 1 ? " question" : " questions") + " left today.";
          }
          setBusy(false);
          finishedState();
          input.focus();
          return;
        }
        var msg = data && data.message ? String(data.message) : "Something went wrong. Please try again in a little while.";
        if (data && data.error === "rate_limited") msg += " " + retryText(data.retry_after_s);
        if (data && data.error === "resting") msg += " The guide pages work all day: Compare, Issues and Forums are in the menu.";
        fail(msg.trim(), true);
      }).catch(function () {
        clearTimeout(timer);
        fail("We could not reach the assistant. Check your connection and try again. The Compare, Issues and Forums pages still work.", true);
      });
    }

    form.addEventListener("submit", function (e) { e.preventDefault(); ask(input.value); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
    });
    restart.addEventListener("click", reset);
    Array.prototype.forEach.call(chips.querySelectorAll("button[data-q]"), function (b) {
      b.addEventListener("click", function () { ask(b.getAttribute("data-q")); });
    });
    finishedState();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { escapeHtml: escapeHtml, renderMarkdown: renderMarkdown, retryText: retryText };
  } else if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  }
})();
