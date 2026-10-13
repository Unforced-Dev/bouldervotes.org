/* Talk through your vote. Vanilla JS, no cookies, nothing stored.
   The conversation lives only in this page; reloading clears it.

   The gateway sends a structured, checked reply: a short answer that never names a candidate, a
   yes/no tally built from the site's recorded stances, optional side-by-side cards (one shared
   question, every candidate in ballot order, recorded excerpts), a measure card (what a yes and a
   no do, the money and every group on each side) and follow-ups. Everything about a candidate or a
   measure comes from the site's data, never from the AI. This file only renders that reply, safely. */
(function () {
  "use strict";

  var MAX_TURNS = 12;
  var MAX_CHARS = 800;
  // Links in the AI's own words are clickable only on these sites; data links (cards, sources) are https only.
  var TEXT_LINK_HOSTS = /^(?:[a-z0-9-]+\.)*(?:bouldervotes\.org|youtube\.com|youtu\.be|bouldercolorado\.gov|bouldercounty\.gov)$/i;
  var ERROR_TEXT = "Something went wrong with that answer. Please try again, or use the Compare, Issues and Forums pages.";

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Only https links. Links to bouldervotes.org become relative so they stay on whatever host serves this page.
  function safeHref(url) {
    var raw = String(url || "");
    if (!/^https:\/\/[^\s"'<>]+$/i.test(raw)) return "";
    var m = /^https:\/\/(?:www\.)?bouldervotes\.org(\/[^\s]*)?$/i.exec(raw);
    if (m) {
      var path = (m[1] || "/").replace(/^\//, "");
      return path === "" ? "./" : path;
    }
    return raw;
  }

  function linkHtml(url, label) {
    var href = safeHref(url);
    if (!href) return escapeHtml(label);
    var ext = /^https:/.test(href);
    return '<a href="' + escapeHtml(href) + '"' + (ext ? ' rel="noopener noreferrer"' : "") + ">" + escapeHtml(label) + "</a>";
  }

  function linkLabel(url) {
    return /youtu/.test(url || "") ? "watch" : "source";
  }

  // The AI's plain text: escaped, with https links made clickable only on the allowlisted sites.
  function textHtml(s) {
    var out = "", at = 0, re = /https:\/\/[^\s<>"]+[^\s<>".,;:!?)\]']/g, m;
    s = String(s);
    while ((m = re.exec(s))) {
      var host = (/^https:\/\/([^\/?#:]+)/.exec(m[0]) || [])[1] || "";
      out += escapeHtml(s.slice(at, m.index)) + (TEXT_LINK_HOSTS.test(host) ? linkHtml(m[0], m[0].replace(/^https:\/\/(?:www\.)?/, "")) : escapeHtml(m[0]));
      at = m.index + m[0].length;
    }
    return out + escapeHtml(s.slice(at));
  }

  function truncate(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, "") + "…" : s;
  }

  // The caveat line that sits next to every quote: where it is from, the caveat, the link. All from data.
  function caveatHtml(q) {
    var bits = [];
    // "Better Boulder questionnaire" + "From the Better Boulder questionnaire." would say it twice.
    if (q.label && String(q.caveat || "").indexOf(q.label) < 0) bits.push(escapeHtml(q.label));
    var s = bits.join(" · ") + (bits.length ? ". " : "") + escapeHtml(q.caveat || "Check the source.");
    if (q.link) s += " " + linkHtml(q.link, linkLabel(q.link));
    return '<span class="cav">' + s + "</span>";
  }

  function sayHtml(say) {
    return (say || []).map(function (par) {
      return "<p>" + par.map(function (seg) {
        if (seg.t === "link") return linkHtml(seg.href, seg.text);
        return textHtml(seg.text);
      }).join("") + "</p>";
    }).join("");
  }

  // Who said yes / no / gave no yes or no, built by the gateway from the recorded stances. Same form for everyone.
  function tallyHtml(tally) {
    if (!tally || !tally.length) return "";
    return '<div class="tally">' + tally.map(function (t) {
      return "<p><strong>On " + escapeHtml(t.short) + "</strong> <span class=\"tally-src\">(" + escapeHtml(t.source) + ")</span>" +
        t.groups.map(function (g) {
          return ' <span class="tg"><b>' + escapeHtml(g.label) + ":</b> " + g.names.map(function (n) { return linkHtml(n.page, n.name); }).join(", ") + ".</span>";
        }).join("") + "</p>";
    }).join("") + '<p class="tally-note">From each candidate\u2019s recorded yes or no. A missing answer says nothing about a view.</p></div>';
  }

  function badgeHtml(row, q, cmp) {
    if (!q.yesno || !row.answered) return "";
    if (row.badge) return '<span class="badge">Said ' + escapeHtml(row.badge) + "</span>";
    return '<span class="badge none">' + escapeHtml(cmp.no_yesno || "No yes/no on file") + "</span>";
  }

  function lineFlags(l) {
    var f = [];
    if (l.mid_sentence) f.push("Starts mid-sentence.");
    if (l.ends_mid) f.push("Ends mid-sentence.");
    return f.length ? " " + f.join(" ") : "";
  }

  function compareHtml(c) {
    if (!c || !c.questions || !c.questions.length) return "";
    var race = c.race === "council" ? "City council" : "Mayor";
    var h = '<section class="cmp" aria-label="' + escapeHtml(c.label) + ', side by side">';
    h += '<p class="cmp-h"><strong>' + escapeHtml(c.label) + "</strong> · " + race + ": every candidate, ballot order, recorded excerpts. Swipe the row.</p>";
    c.questions.forEach(function (q) {
      // The question header names the forum and date once; each card line keeps its own caveat and link.
      h += '<div class="cmp-q"><p class="cmp-ask">Asked of every candidate (' + escapeHtml(q.label) + "): <q>" + escapeHtml(truncate(q.question, 220)) + "</q></p>";
      h += '<div class="cards" role="list">';
      q.rows.forEach(function (r) {
        h += '<article class="card' + (r.answered ? "" : " empty") + '" role="listitem"><p class="who"><span>' + linkHtml(r.page, r.name) +
          '</span> <span class="pos">#' + escapeHtml(r.ballot_position) + "</span></p>" + badgeHtml(r, q, c);
        if (!r.answered) {
          h += '<p class="none">' + escapeHtml(c.no_answer || "No answer to this question on file.") + "</p>";
        } else {
          r.lines.forEach(function (l) {
            if (l.text === null || l.text === undefined) {
              h += '<p class="none">This line couldn\u2019t be checked just now. ' + linkHtml(r.page, "See " + r.name + "\u2019s page") + ".</p>";
              return;
            }
            h += "<blockquote><p>\u201c" + escapeHtml(l.text) + "\u201d</p></blockquote>" +
              '<p class="cav-line">' + caveatHtml({ caveat: (l.caveat || "Check the source.") + lineFlags(l), link: l.link }) + "</p>";
          });
        }
        h += "</article>";
      });
      h += "</div></div>";
    });
    h += '<p class="cmp-foot">These are recorded excerpts, not full answers. A missing answer says nothing about a candidate\u2019s view. ' + linkHtml(c.page, "Compare page") + "</p></section>";
    return h;
  }

  function groupList(gs) {
    if (!gs || !gs.length) return "none on file";
    return gs.map(function (g) {
      return linkHtml(g.link, g.name) + (g.date ? " (" + escapeHtml(g.date) + ")" : "") + (g.note ? " [" + escapeHtml(g.note) + "]" : "");
    }).join("; ");
  }

  // A ballot measure, from the site's data: what a yes and a no do; money, groups and wording behind "Show sources".
  function measureHtml(m) {
    if (!m) return "";
    var h = '<section class="msr" aria-label="Measure ' + escapeHtml(m.letter) + '">';
    h += '<p class="msr-h"><strong>' + escapeHtml(m.letter) + ": " + escapeHtml(m.title) + "</strong></p>";
    h += "<p><strong>A yes vote:</strong> " + escapeHtml(m.yes_means) + "</p><p><strong>A no vote:</strong> " + escapeHtml(m.no_means) + "</p>";
    var li = [];
    if (m.money) li.push("<li><p><strong>Money:</strong> " + escapeHtml(m.money.text) + " " + linkHtml(m.money.link, "city source") + "</p></li>");
    if (m.groups) {
      li.push("<li><p><strong>Supports:</strong> " + groupList(m.groups.supports) + "</p></li>");
      li.push("<li><p><strong>Opposes:</strong> " + groupList(m.groups.opposes) + "</p></li>");
    }
    li.push("<li><p>" + linkHtml(m.official, "Official ballot wording") + " · " + linkHtml(m.page, m.letter + " page") + "</p></li>");
    h += '<details class="srcs"><summary>Show sources</summary><ul>' + li.join("") + "</ul></details></section>";
    return h;
  }

  function pagesHtml(pages) {
    if (!pages || !pages.length) return "";
    return '<p class="pages">Everything on file: ' + pages.map(function (x) { return linkHtml(x.page, x.name); }).join(", ") + ".</p>";
  }

  function nextHtml(next) {
    if (!next || !next.length) return "";
    return '<div class="next" role="group" aria-label="Follow-up questions">' + next.map(function (q) {
      return '<button type="button" class="chip" data-q="' + escapeHtml(q) + '">' + escapeHtml(q) + "</button>";
    }).join("") + "</div>";
  }

  // One guide message from the gateway's checked reply. No reply object: a neutral error, never raw text.
  function renderReply(data) {
    var r = data && data.reply;
    if (!r || !r.say) return '<div class="say"><p>' + escapeHtml(ERROR_TEXT) + "</p></div>";
    return '<div class="say">' + sayHtml(r.say) + "</div>" + tallyHtml(r.tally) + measureHtml(r.measure) + compareHtml(r.compare) +
      pagesHtml(r.pages) + nextHtml(r.next);
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
    var starters = document.getElementById("chat-chips");
    var count = document.getElementById("chat-count");
    var messages = [];
    var busy = false;

    root.hidden = false;

    function add(cls, html) {
      var d = document.createElement("div");
      d.className = cls;
      d.innerHTML = html;
      log.appendChild(d);
      return d;
    }

    function turnsUsed() {
      return messages.filter(function (m) { return m.role === "user"; }).length;
    }

    function setBusy(on) {
      busy = on;
      send.disabled = on;
      root.setAttribute("aria-busy", on ? "true" : "false");
      status.textContent = on ? "The guide is checking the record…" : "";
    }

    function finishedState() {
      var done = turnsUsed() >= MAX_TURNS;
      input.disabled = done;
      send.disabled = done || busy;
      restart.hidden = turnsUsed() === 0;
      starters.hidden = turnsUsed() > 0;
      if (done) status.textContent = "That is the limit for one conversation (" + MAX_TURNS + " messages). Choose “Start over” to begin a new one.";
    }

    function clearNext() {
      Array.prototype.forEach.call(log.querySelectorAll(".next"), function (n) { n.parentNode.removeChild(n); });
    }

    function reset() {
      messages = [];
      log.innerHTML = "";
      input.value = "";
      input.disabled = false;
      count.textContent = "";
      status.textContent = "";
      finishedState();
      input.focus();
    }

    function ask(question, shown) {
      question = String(question || "").replace(/\s+/g, " ").trim();
      if (!question || busy || turnsUsed() >= MAX_TURNS) return;
      if (question.length > MAX_CHARS) { status.textContent = "Please keep your message under " + MAX_CHARS + " characters."; return; }
      clearNext();
      messages.push({ role: "user", content: question });
      var bubble = add("m-user", escapeHtml(shown || question));
      var pending = add("m-guide", '<div class="typing" aria-hidden="true"><i></i><i></i><i></i></div>');
      pending.scrollIntoView({ block: "nearest" });
      input.value = "";
      setBusy(true);
      finishedState();

      function fail(text, restore) {
        messages.pop();
        [bubble, pending].forEach(function (n) { if (n && n.parentNode) n.parentNode.removeChild(n); });
        if (restore) input.value = question;
        add("m-notice", escapeHtml(text));
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
        if (r.res.ok && data && data.ok && typeof data.answer === "string" && data.reply && data.reply.say) {
          messages.push({ role: "assistant", content: data.answer });
          pending.innerHTML = renderReply(data);
          pending.classList.add("in");
          pending.scrollIntoView({ block: "start" });
          if (data.remaining && typeof data.remaining.day === "number" && data.remaining.day <= 5) {
            count.textContent = data.remaining.day + (data.remaining.day === 1 ? " question" : " questions") + " left today.";
          }
          setBusy(false);
          finishedState();
          return;
        }
        var msg = data && data.message && !data.ok ? String(data.message) : ERROR_TEXT;
        if (data && data.error === "rate_limited") msg += " " + retryText(data.retry_after_s);
        if (data && data.error === "resting") msg += " The guide pages work all day: Compare, Issues and Forums are in the menu.";
        fail(msg.trim(), true);
      }).catch(function () {
        clearTimeout(timer);
        fail("We could not reach the guide. Check your connection and try again. The Compare, Issues and Forums pages still work.", true);
      });
    }

    form.addEventListener("submit", function (e) { e.preventDefault(); ask(input.value); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
    });
    restart.addEventListener("click", reset);
    Array.prototype.forEach.call(starters.querySelectorAll("button[data-q]"), function (b) {
      b.addEventListener("click", function () { ask(b.getAttribute("data-q"), b.getAttribute("data-label")); });
    });
    log.addEventListener("click", function (e) {
      var b = e.target && e.target.closest ? e.target.closest("button[data-q]") : null;
      if (b) ask(b.getAttribute("data-q"));
    });
    finishedState();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { escapeHtml: escapeHtml, safeHref: safeHref, renderReply: renderReply, retryText: retryText };
  } else if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  }
})();
